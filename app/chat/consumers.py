import json
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from .models import Message, Room, DirectMessage, DirectThread
import asyncio
from redis.asyncio import Redis
from django.conf import settings
from datetime import datetime, timezone
from typing import Optional, Set

User = get_user_model()


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        self.room_name = self.scope["url_route"]["kwargs"]["room_name"]
        self.room_group_name = f"chat_{self.room_name}"

        if await self.room_exists(self.room_name):
            await self.channel_layer.group_add(self.room_group_name, self.channel_name)
            await self.accept()
        else:
            await self.close(code=4004)

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data or "{}")
        content = (data.get("message") or "").strip()
        room_name = data.get("room_name")

        # ✅ Accept either key; use OR so reply_to works when reply_to_id is null
        raw_reply = data.get("reply_to_id") or data.get("reply_to")
        try:
            reply_to_id = int(raw_reply) if raw_reply is not None else None
        except (TypeError, ValueError):
            reply_to_id = None

        if not content or not room_name:
            return

        # Do all ORM + decryption inside a sync thread and get a JSON-serializable dict
        event = await self.create_message_and_event(
            username=self.user.username,
            message=content,
            room_name=room_name,
            reply_to_id=reply_to_id,
        )

        await self.channel_layer.group_send(self.room_group_name, event)

    async def chat_message(self, event):
        await self.send(text_data=json.dumps(event))

    # ----------------- DB helpers -----------------

    @database_sync_to_async
    def room_exists(self, room_name: str) -> bool:
        return Room.objects.filter(name=room_name).exists()

    @database_sync_to_async
    def create_message_and_event(
        self, *, username: str, message: str, room_name: str, reply_to_id: int | None
    ) -> dict:
        user = User.objects.filter(username=username).only("id", "username").first()
        room = Room.objects.filter(name=room_name).only("id", "encryption_key").first()

        # Save message; assign FK by id (no fetch needed)
        msg = Message.objects.create(
            sender=user,
            message=message,          # if you encrypt on save, this will be ciphertext in DB
            room=room,
            reply_to_id=reply_to_id,
        )

        try:
            decrypted_message = msg.get_decrypted_message()
        except Exception:
            decrypted_message = msg.message 

        # Resolve + decrypt reply preview if present
        reply_username = None
        reply_preview = None
        if reply_to_id:
            try:
                reply_obj = (
                    Message.objects.select_related("sender", "room")
                    .only("id", "message", "sender__username", "room__encryption_key")
                    .get(pk=reply_to_id)
                )
                reply_username = reply_obj.sender.username if reply_obj.sender_id else None
                try:
                    reply_preview = reply_obj.get_decrypted_message()[:140]
                except Exception:
                    reply_preview = (reply_obj.message or "")[:140]
            except ObjectDoesNotExist:
                reply_username = None
                reply_preview = None

        # Return primitives only
        return {
            "type": "chat_message",
            "messageId": msg.pk,                   # UI uses camelCase
            "id": msg.pk,                          # fallback for other clients
            "username": user.username if user else "",
            "message": decrypted_message,          # ✅ decrypted outbound text
            "created_at": msg.created_at.isoformat(),
            "reply_to": reply_to_id,
            "reply_to_username": reply_username,
            "reply_to_preview": reply_preview,     # ✅ decrypted preview when applicable
        }


# ---------- Presence storage (Redis) ----------
REDIS: Redis = Redis.from_url(getattr(settings, "PRESENCE_REDIS_URL", "redis://redis:6379/1"))

ONLINE_TTL = 45        # seconds considered "online" without a heartbeat
HEARTBEAT_EVERY = 15   # how often to refresh TTL and last_seen


def _k_conn(conn_id: str) -> str:
    return f"presence:conn:{conn_id}"           # HASH { user_id, thread }

def _k_user(user_id: int) -> str:
    return f"presence:user:{user_id}"           # SET of conn_ids

def _k_thread(thread_uuid: str) -> str:
    return f"presence:thread:{thread_uuid}"     # SET of conn_ids

def _k_last_seen(user_id: int) -> str:
    return f"presence:last_seen:{user_id}"      # STRING ISO8601 (UTC)


def _now_iso() -> str:
    """UTC ISO-8601 with a 'Z' suffix, e.g. 2025-08-21T12:34:56.789Z"""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def _mark_online(user_id: int, thread_uuid: str, conn_id: str):
    """Mark one websocket connection online and stamp last_seen."""
    async with REDIS.pipeline(transaction=True) as p:
        await (
            p.sadd(_k_user(user_id), conn_id)
             .sadd(_k_thread(thread_uuid), conn_id)
             .hset(_k_conn(conn_id), mapping={"user_id": user_id, "thread": thread_uuid})
             .expire(_k_conn(conn_id), ONLINE_TTL)
             .set(_k_last_seen(user_id), _now_iso())
             .execute()
        )


async def _touch(user_id: int, conn_id: str):
    """Refresh one connection TTL and the user's last_seen."""
    async with REDIS.pipeline(transaction=True) as p:
        await (
            p.expire(_k_conn(conn_id), ONLINE_TTL)
             .set(_k_last_seen(user_id), _now_iso())
             .execute()
        )


async def _mark_offline(user_id: int, thread_uuid: str, conn_id: str):
    """Remove one websocket connection and stamp last_seen once more."""
    async with REDIS.pipeline(transaction=True) as p:
        await (
            p.srem(_k_user(user_id), conn_id)
             .srem(_k_thread(thread_uuid), conn_id)
             .delete(_k_conn(conn_id))
             .set(_k_last_seen(user_id), _now_iso())
             .execute()
        )


async def _thread_online_user_ids(thread_uuid: str) -> Set[int]:
    """
    Return unique user_ids in this DM thread with any live connection.
    Uses existence of connection hashes as truth for 'online'.
    """
    conns = await REDIS.smembers(_k_thread(thread_uuid))
    if not conns:
        return set()

    # Normalize to str
    conn_ids = [(c.decode() if isinstance(c, (bytes, bytearray)) else c) for c in conns]

    pipe = REDIS.pipeline(transaction=False)
    for c in conn_ids:
        pipe.exists(_k_conn(c))
        pipe.hget(_k_conn(c), "user_id")
    res = await pipe.execute()

    ids: Set[int] = set()
    for i in range(0, len(res), 2):
        exists, uid = res[i], res[i + 1]
        if exists and uid is not None:
            if isinstance(uid, (bytes, bytearray)):
                uid = uid.decode()
            try:
                ids.add(int(uid))
            except (TypeError, ValueError):
                pass
    return ids


class DirectMessageConsumer(AsyncWebsocketConsumer):
    """
    Endpoint for ws://.../ws/chat/<room_uuid>/
    where room_uuid is DirectThread.uuid
    """

    # --------------- Lifecycle ---------------

    async def connect(self):
        self.room_name = self.scope["url_route"]["kwargs"]["chat"]
        self.user = self.scope.get("user")

        thread = await self._get_thread()
        if not thread:
            await self.close(code=4404)
            return
        if not await self._user_in_thread(thread):
            await self.close(code=4403)
            return

        self.thread = thread
        self.group_name = f"dm_{self.room_name}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # ---------- PRESENCE: mark online, start heartbeat, notify both sides ----------
        self.user_id: Optional[int] = getattr(self.user, "id", None)
        self.conn_id: str = self.channel_name

        if self.user_id:
            await _mark_online(self.user_id, self.room_name, self.conn_id)
            self._hb_task = asyncio.create_task(self._heartbeat())

            # Send a presence snapshot to THIS socket
            await self._send_presence_snapshot()

            # Broadcast updated presence to the thread participants
            await self._broadcast_presence()

    async def disconnect(self, close_code):
        try:
            if hasattr(self, "group_name"):
                await self.channel_layer.group_discard(self.group_name, self.channel_name)
        finally:
            # ---------- PRESENCE cleanup (TTL covers hard drops) ----------
            if getattr(self, "user_id", None):
                await _mark_offline(self.user_id, self.room_name, self.conn_id)
            if hasattr(self, "_hb_task"):
                self._hb_task.cancel()
            await self._broadcast_presence()

    # --------------- Messages ---------------

    async def receive(self, text_data=None, bytes_data=None):
        try:
            data = json.loads(text_data or "{}")
        except Exception:
            return

        # Client can explicitly request a fresh presence snapshot
        if data.get("action") == "presence.list":
            await self._send_presence_snapshot()
            return

        text = (data.get("message") or "").strip()
        if not text:
            return

        reply_to_id = data.get("reply_to")
        msg = await self._create_message(text, reply_to_id)
        if not msg:
            return

        payload = await self._message_to_payload(msg)
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "chat.message", "payload": payload},
        )

    async def chat_message(self, event):
        # maps from type "chat.message"
        await self.send(text_data=json.dumps(event["payload"]))

    # --------------- Presence events ---------------

    async def presence_update(self, event):
        # Push a normalized presence payload the client can consume
        await self.send(text_data=json.dumps(event["payload"]))

    # --------------- Presence helpers ---------------

    async def _heartbeat(self):
        """Periodic TTL refresh + last_seen update while the socket is alive."""
        try:
            while True:
                await _touch(self.user_id, self.conn_id)
                await asyncio.sleep(HEARTBEAT_EVERY)
        except asyncio.CancelledError:
            pass

    async def _send_presence_snapshot(self):
        """Send presence only to this socket."""
        ids = await _thread_online_user_ids(self.room_name)
        payload = await self._presence_payload(ids)
        await self.send(text_data=json.dumps(payload))

    async def _broadcast_presence(self):
        """Notify both participants via the group."""
        ids = await _thread_online_user_ids(self.room_name)
        payload = await self._presence_payload(ids)
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "presence.update", "payload": payload},
        )

    async def _presence_payload(self, online_ids: Set[int]) -> dict:
        """
        Build a compact, DM-specific presence payload.
        Includes the peer's explicit last_seen ISO string (UTC) if available.
        """
        a = self.thread.user_a
        b = self.thread.user_b
        a_id, b_id = a.id, b.id
        a_name, b_name = a.username, b.username

        me_id = getattr(self.user, "id", None)
        peer_id = b_id if me_id == a_id else a_id
        peer_name = b_name if me_id == a_id else a_name

        me_online = (me_id in online_ids) if me_id else False
        peer_online = (peer_id in online_ids)

        # Fetch peer's last seen timestamp (ISO string) from Redis
        peer_last_seen = await REDIS.get(_k_last_seen(peer_id))
        if isinstance(peer_last_seen, (bytes, bytearray)):
            peer_last_seen = peer_last_seen.decode()

        return {
            "type": "presence",
            "thread": self.room_name,
            "online_user_ids": list(online_ids),   # deduped user IDs currently online in this DM
            "me_id": me_id,
            "me_online": me_online,
            "peer_id": peer_id,
            "peer_username": peer_name,
            "peer_online": peer_online,
            "online_map": {
                str(a_id): (a_id in online_ids),
                str(b_id): (b_id in online_ids),
            },
            "last_seen": peer_last_seen,           # <— client uses this if peer_online is False
        }

    # --------------- DB helpers ---------------

    @database_sync_to_async
    def _get_thread(self) -> Optional[DirectThread]:
        try:
            return DirectThread.objects.select_related("user_a", "user_b").get(uuid=self.room_name)
        except DirectThread.DoesNotExist:
            return None

    @database_sync_to_async
    def _user_in_thread(self, thread: DirectThread) -> bool:
        u = getattr(self, "user", None)
        if not u or not u.is_authenticated:
            return False
        return u.id in (thread.user_a_id, thread.user_b_id)

    @database_sync_to_async
    def _create_message(self, text: str, reply_to_id: Optional[int]):
        u = getattr(self, "user", None)
        if not u or not u.is_authenticated:
            return None
        thread = DirectThread.objects.only("id", "user_a_id", "user_b_id").get(uuid=self.room_name)
        if u.id not in (thread.user_a_id, thread.user_b_id):
            return None
        reply_obj = None
        if reply_to_id:
            reply_obj = DirectMessage.objects.filter(id=reply_to_id, thread=thread).first()
        return DirectMessage.objects.create(thread=thread, sender=u, message=text, reply_to=reply_obj)

    @database_sync_to_async
    def _message_to_payload(self, msg: DirectMessage):
        return msg.to_ws_payload()

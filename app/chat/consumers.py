import json
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from .models import Message, Room

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
        # Fan out unchanged
        await self.send(text_data=json.dumps(event))

    # ----------------- DB helpers -----------------

    @database_sync_to_async
    def room_exists(self, room_name: str) -> bool:
        return Room.objects.filter(name=room_name).exists()

    @database_sync_to_async
    def create_message_and_event(
        self, *, username: str, message: str, room_name: str, reply_to_id: int | None
    ) -> dict:
        """
        Create Message with reply_to_id if given.
        Build event with resolved + decrypted fields (all inside sync context).
        """
        user = User.objects.filter(username=username).only("id", "username").first()
        room = Room.objects.filter(name=room_name).only("id", "encryption_key").first()

        # Save message; assign FK by id (no fetch needed)
        msg = Message.objects.create(
            sender=user,
            message=message,          # if you encrypt on save, this will be ciphertext in DB
            room=room,
            reply_to_id=reply_to_id,
        )

        # Decrypt the just-saved message for broadcasting
        try:
            decrypted_message = msg.get_decrypted_message()
        except Exception:
            decrypted_message = msg.message  # fallback if no key or decryption error

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

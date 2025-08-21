from django.db import models
from django.contrib.auth.models import User
from cryptography.fernet import Fernet
from datetime import datetime
from django.utils import timezone
import uuid
from django.db import transaction


def generate_key():
    return Fernet.generate_key().decode()


class Room(models.Model):
    name = models.CharField(max_length=120, null=True, blank=False)
    creator = models.ForeignKey(User, blank=False, null=True, on_delete=models.CASCADE, related_name="room_creator")
    granted_users = models.ManyToManyField(User, blank=True)
    encryption_key = models.CharField(max_length=44, blank=False, default=generate_key)

    def __str__(self):
        return self.name

class Message(models.Model):
    reply_to = models.ForeignKey('self', null=True, on_delete=models.SET_NULL, related_name='replies')
    sender = models.ForeignKey(User, blank=False, null=True, on_delete=models.CASCADE, related_name="message_sender")
    room = models.ForeignKey(Room, blank=False, null=True, on_delete=models.CASCADE)
    message = models.TextField()
    created_at = models.DateTimeField(default=datetime.now)

    def __str__(self):
        return f"{self.room.name} | {self.sender.username}"
    
    def save(self, *args, **kwargs):
        if self.room.encryption_key:
            fernet = Fernet(self.room.encryption_key.encode())
            self.message = fernet.encrypt(self.message.encode()).decode()
        return super().save(*args, **kwargs)

    def get_decrypted_message(self):
        if self.room.encryption_key:
            fernet = Fernet(self.room.encryption_key.encode())
            return fernet.decrypt(self.message.encode()).decode()
        return self.message


class DirectThread(models.Model):
    """A 1:1 conversation between exactly two users."""
    id = models.BigAutoField(primary_key=True)
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    user_a = models.ForeignKey(User, on_delete=models.CASCADE, related_name="dm_threads_a")
    user_b = models.ForeignKey(User, on_delete=models.CASCADE, related_name="dm_threads_b")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user_a", "user_b"], name="unique_dm_pair_ordered"),
            models.CheckConstraint(check=~models.Q(user_a=models.F("user_b")), name="dm_distinct_users"),
        ]

    def save(self, *args, **kwargs):
        # Normalize order to keep uniqueness independent of order
        if self.user_a_id and self.user_b_id and self.user_a_id > self.user_b_id:
            self.user_a_id, self.user_b_id = self.user_b_id, self.user_a_id
        super().save(*args, **kwargs)

    @classmethod
    def get_or_create_for_users(cls, u1, u2) -> "DirectThread":
        ua, ub = (u1, u2) if u1.id < u2.id else (u2, u1)
        obj, _ = cls.objects.get_or_create(user_a=ua, user_b=ub)
        return obj

    def participants(self):
        return (self.user_a, self.user_b)

    def __str__(self):
        return f"DM({self.user_a_id},{self.user_b_id})#{self.uuid}"


class DirectMessage(models.Model):
    id = models.BigAutoField(primary_key=True)
    thread = models.ForeignKey(DirectThread, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name="dm_messages_sent")
    message = models.TextField()
    reply_to = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="replies")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["thread", "created_at"])]

    def clean(self):
        if self.reply_to and self.reply_to.thread_id != self.thread_id:
            from django.core.exceptions import ValidationError
            raise ValidationError("reply_to message must belong to the same thread")

    def save(self, *args, **kwargs):
        self.full_clean()
        with transaction.atomic():
            super().save(*args, **kwargs)
            DirectThread.objects.filter(pk=self.thread_id).update(last_message_at=timezone.now())

    def to_ws_payload(self):
        payload = {
            "id": self.id,
            "room_name": str(self.thread.uuid),
            "username": getattr(self.sender, "username", None),
            "message": self.message,
            "created_at": self.created_at.isoformat(),
        }
        if self.reply_to_id:
            payload.update({
                "reply_to": self.reply_to_id,
                "reply_to_message": self.reply_to.message,
                "reply_to_username": getattr(self.reply_to.sender, "username", None),
            })
        return payload

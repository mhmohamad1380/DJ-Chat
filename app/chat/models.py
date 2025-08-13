from django.db import models
from django.contrib.auth.models import User
from cryptography.fernet import Fernet
from datetime import datetime

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
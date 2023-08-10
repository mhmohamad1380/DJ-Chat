from django.db import models
from django.contrib.auth.models import User


class Room(models.Model):
    name = models.CharField(max_length=120, null=True, blank=False)
    creator = models.ForeignKey(User, blank=False, null=True, on_delete=models.CASCADE, related_name="room_creator")
    granted_users = models.ManyToManyField(User, blank=True)

    def __str__(self):
        return self.name

class Message(models.Model):
    sender = models.ForeignKey(User, blank=False, null=True, on_delete=models.CASCADE, related_name="message_sender")
    room = models.ForeignKey(Room, blank=False, null=True, on_delete=models.CASCADE)
    message = models.TextField()

    def __str__(self):
        return f"{self.room.name} | {self.sender.username}"

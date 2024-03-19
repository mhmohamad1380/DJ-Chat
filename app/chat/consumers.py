import json
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth import get_user_model
from .models import Message, Room
from django.shortcuts import redirect


class ChatConsumer(AsyncWebsocketConsumer):
    
    async def connect(self):
        self.user = self.scope["user"]
        self.room_name = self.scope["url_route"]["kwargs"]["room_name"]
        self.room_group_name = "chat_%s" % self.room_name


        # Join room group
        if await self.check_room_availability:
            await self.channel_layer.group_add(self.room_group_name, self.channel_name)
            await self.accept()
        else:
            raise ValueError("this room doesn't exist!")
        


    @database_sync_to_async
    def create_message(self, username, message, room):
        User = get_user_model()
        user = User.objects.filter(username=username).first()
        room = Room.objects.filter(name=room).first()
        Message.objects.create(sender=user, message=message, room=room)
        return 1

    @property
    @database_sync_to_async
    def check_room_availability(self):
        return Room.objects.filter(name=self.room_name).exists()
    

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    # Receive message from WebSocket
    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        message = text_data_json["message"]
        room_name = text_data_json['room_name']

        # Send message to room group
        await self.channel_layer.group_send(
            self.room_group_name, {"type": "chat_message",
                                    "message": message, 
                                    "username": self.user.username,
                                    "room": room_name
            }
        )

    # Receive message from room group
    async def chat_message(self, event):
        message = event["message"]
        username = event['username']
        room = event['room']
        auth_username = self.scope['user'].username

        new_message = await self.create_message(username=username, message=message, room=room)

        # Send message to WebSocket
        await self.send(text_data=json.dumps({"message": message, "username": username, "auth_username": auth_username}))

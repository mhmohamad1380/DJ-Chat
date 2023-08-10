from django.contrib import admin
from .models import Message, Room

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    pass

@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    pass
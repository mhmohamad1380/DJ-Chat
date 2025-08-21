from django.contrib import admin
from chat.models import Message, Room, DirectThread, DirectMessage

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    pass

@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    pass

@admin.register(DirectThread)
class DirectThreadAdmin(admin.ModelAdmin):
    list_display = ("uuid", "user_a", "user_b", "last_message_at", "created_at")
    search_fields = ("uuid", "user_a__username", "user_b__username")

@admin.register(DirectMessage)
class DirectMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "thread", "sender", "short_msg", "created_at")
    list_filter = ("thread",)
    search_fields = ("message", "sender__username")

    def short_msg(self, obj):
        return (obj.message[:60] + "…") if len(obj.message) > 60 else obj.message
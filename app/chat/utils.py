from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from chat.models import DirectThread, DirectMessage
from cryptography.fernet import Fernet

UserModel = get_user_model()


def open_dm_with_username(current_user, target_username: str) -> DirectThread:
    if not target_username:
        raise ValidationError("username is required")
    try:
        other = UserModel.objects.get(username=target_username)
    except ObjectDoesNotExist:
        raise ValidationError("User not found")
    if other.id == getattr(current_user, "id", None):
        raise ValidationError("You can't DM yourself")
    return DirectThread.get_or_create_for_users(current_user, other)


def send_direct_message(from_user, to_username, text, reply_to_id=None) -> DirectMessage:
    other = UserModel.objects.get(username=to_username)
    thread = DirectThread.get_or_create_for_users(from_user, other)
    reply_obj = None
    if reply_to_id:
        reply_obj = DirectMessage.objects.filter(id=reply_to_id, thread=thread).first()
    return DirectMessage.objects.create(thread=thread, sender=from_user, message=text, reply_to=reply_obj)

def get_decrypted_message(message, key=None):
        if key:
            fernet = Fernet(key.encode())
            return fernet.decrypt(message.encode()).decode()
        return message
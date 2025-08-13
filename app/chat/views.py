from django.shortcuts import render, redirect, get_object_or_404
from django.http.response import Http404, HttpResponse, HttpResponseForbidden
from .models import Room, Message
from slugify import slugify
from django.conf import settings
from django_ratelimit.decorators import ratelimit
from django.contrib.auth import get_user_model
User = get_user_model()

# Create your views here.

def index(request):
    if not request.user.is_authenticated:
        return redirect("/user/register/")
    return render(request, "chat/index.html")



@ratelimit(key="user_or_ip", rate="10/m")
def room(request, room_name):
    # Require auth
    if not request.user.is_authenticated:
        return redirect("/user/register/")

    # Get room (case-insensitive), with granted users prefetched
    try:
        room = Room.objects.prefetch_related("granted_users").get(name__iexact=room_name)
    except Room.DoesNotExist:
        return render(request, 'chat/404.html')

    # Access control (efficient membership check)
    if not room.granted_users.filter(pk=request.user.pk).exists():
        return render(request, 'chat/404.html')

    # Pull messages with everything the template needs (efficiently)
    messages_qs = (
        Message.objects.filter(room=room)
        .select_related("room", "sender", "reply_to", "reply_to__sender")
        .order_by("created_at")
    )

    # Decrypt text for display while keeping model instances
    messages = list(messages_qs)
    for m in messages:
        try:
            # Show decrypted message in the template via {{ message.message }}
            m.message = m.get_decrypted_message()
            if m.reply_to:
                m.reply_to.message = m.reply_to.get_decrypted_message()
        except Exception:
            # Fallback to stored (possibly plaintext) value
            pass

    return render(
        request,
        "chat/room.html",
        {
            "room_name": room.name,
            "messages": messages,                 # model instances (reply_to available)
            "username": str(request.user.username),
        },
    )


def home_redirect(request):
    return redirect("/chat")

@ratelimit(key="user_or_ip", rate="2/m")
def create_room(request, room_name):
    if not request.user.is_authenticated:
        return redirect("/")
    
    prefetched_room = Room.objects.prefetch_related("granted_users")

    if prefetched_room.filter(creator=request.user).count() >= settings.MAXIMUM_ROOM_ALLOWED:
        return HttpResponseForbidden(f"You have created maximum {settings.MAXIMUM_ROOM_ALLOWED} rooms before!")
    
    if prefetched_room.filter(name=room_name).exists():
        return HttpResponseForbidden("this room exists!")
    
    room = Room.objects.create(name=slugify(text=room_name), creator=request.user)
    room.granted_users.set([request.user])


    return render(request, 'chat/200.html')

def user_rooms_list(request):
    if not request.user.is_authenticated:
        return redirect("/user/register/")
    
    rooms = Room.objects.prefetch_related("granted_users").filter(granted_users__in=[request.user]).all()
    return render(request, "chat/invite.html", context={"rooms": rooms})

def user_invite(request):
    if not request.user.is_authenticated:
        return redirect("/user/register/")
    
    room_pk = request.POST.get("room")
    username = request.POST.get("username")
    room = Room.objects.prefetch_related("granted_users").get(pk=room_pk, granted_users__in=[request.user])
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return HttpResponse("this User does not exist!")

    try:
        room.granted_users.add(user)
        room.save()
    except:
        return HttpResponse("something went wrong!")
    
    return HttpResponse("the User has been Invited successfully :)")


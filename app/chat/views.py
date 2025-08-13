from django.shortcuts import render, redirect
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
    room = Room.objects.filter(name__iexact=room_name)
    if not request.user.is_authenticated:
        return redirect("/user/register/")
    if not room.exists():
        raise Http404("this room does not exist!")
    
    if not request.user in room.first().granted_users.all():
        return HttpResponse("You do not have access!")
    
    messages = Message.objects.filter(room__name=room_name).order_by('created_at').all()
    messages = [
        {
            "sender": message.sender,
            "message": message.get_decrypted_message()
        } for message in messages
    ]
    return render(request, "chat/room.html", {"room_name": room_name, "messages": messages, "username": str(request.user.username)})


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


    return HttpResponse(f"the room with name: {room.name} has successfully created!")

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


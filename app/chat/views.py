from django.shortcuts import render, redirect, get_object_or_404
from django.http.response import Http404, HttpResponse, HttpResponseForbidden
from chat.models import Room, Message, DirectThread, DirectMessage
from slugify import slugify
from django.conf import settings
from django_ratelimit.decorators import ratelimit
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.http import HttpRequest, HttpResponseBadRequest
from django.core.exceptions import ValidationError
from chat.utils import open_dm_with_username, get_decrypted_message
from django.db.models import Q, Subquery, OuterRef

User = get_user_model()

# Create your views here.

def index(request):
    if not request.user.is_authenticated:
        return redirect("/user/register/")
    return render(request, "chat/homepage.html")



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
            "users": room.granted_users.exclude(pk=request.user.pk).values('username')
        },
    )


def home_redirect(request):
    return redirect("/chat/home")

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




@login_required
def dm_start(request: HttpRequest, username: str):
    try:
        thread = open_dm_with_username(request.user, username)
    except ValidationError as exc:
        return HttpResponseBadRequest(str(exc))
    return redirect("dm_room", room_name=str(thread.uuid))

@login_required
def dm_room_view(request: HttpRequest, room_name: str):
    thread = DirectThread.objects.get(uuid=room_name)
    if request.user.id not in (thread.user_a_id, thread.user_b_id):
        return HttpResponseBadRequest("Forbidden")
    messages_qs = thread.messages.select_related("sender", "reply_to", "reply_to__sender").order_by("created_at", "id")[:200]
    context = {
        "room_name": str(thread.uuid),
        "username": request.user.username,
        "other_user": thread.user_b if thread.user_a_id == request.user.id else thread.user_a,
        "messages": messages_qs,
    }
    return render(request, "chat/one-to-one.html", context)


@login_required(login_url='/user/login/')
def chats_homepage(request):
    user = request.user

    rooms = Room.objects.filter(granted_users=user).annotate(
        last_message=Subquery(
            Message.objects.filter(room_id=OuterRef('pk')).order_by('-created_at').values('message')[:1]
        )
    )

    chats = DirectThread.objects.filter(
        Q(user_a=user) |
        Q(user_b=user)
    ).annotate(
        last_message=Subquery(
            DirectMessage.objects.filter(thread_id=OuterRef('pk')).order_by('-created_at').values('message')[:1]
        )
    )

    rooms = list(rooms)
    for room in rooms:
        room.last_message = get_decrypted_message(room.last_message, room.encryption_key)

    return render(request, 'chat/homepage.html', context={'rooms': rooms, 'chats': chats})


@login_required
def user_start_chat(request: HttpRequest):
    return render(request, "chat/start_chat.html")
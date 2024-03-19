from django.urls import path

from . import views


urlpatterns = [
    path("", views.index, name="index"),
    path("<str:room_name>/", views.room, name="room"),
    path("room/create/<str:room_name>/", views.create_room, name="room"),
    path("user/invite/", views.user_rooms_list, name='user_rooms_list'),
    path("user/invite/submit/", views.user_invite, name="user-invite-submit")
]
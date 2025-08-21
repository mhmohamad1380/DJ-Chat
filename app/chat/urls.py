from django.urls import path

from . import views


urlpatterns = [
    path('home/', views.chats_homepage, name='home_page'),
    # path("", views.index, name="index"),
    path("<str:room_name>/", views.room, name="room"),
    path("room/create/<str:room_name>/", views.create_room, name="room"),
    path("user/invite/", views.user_rooms_list, name='user_rooms_list'),
    path("user/invite/submit/", views.user_invite, name="user-invite-submit"),
    path("dm/start/", views.user_start_chat, name="dm_start"),
    path("dm/start/<str:username>/", views.dm_start, name="dm_start"),
    path("dm/<str:room_name>/", views.dm_room_view, name="dm_room"),
]
from django.urls import path
from . import views

urlpatterns = [
    path("", views.root, name="root"),
    path("login", views.login_view, name="login"),
    path("register", views.register_view, name="register"),
    path("logout", views.logout_view, name="logout"),
    path("home", views.home, name="home"),
    path("notifications", views.notifications_view, name="notifications"),
    path("profile-edit", views.profile_edit_view, name="profile_edit"),
    path("search", views.search_view, name="search"),
    path("friends", views.friends_view, name="friends"),
    path("new-post", views.new_post_view, name="new_post"),
    path("chat", views.chat_view, name="chat"),
    path("profile", views.profile_view, name="profile"),
    path("user-profile/<str:username>", views.user_profile_view, name="user_profile"),
    path("user/<str:username>/follow-toggle", views.follow_toggle, name="follow_toggle"),
    # Post endpoints
    path("post/<str:post_uid>/like", views.post_like_toggle, name="post_like_toggle"),
    path("post/<str:post_uid>/comments", views.post_comments_json, name="post_comments_json"),
    path("post/<str:post_uid>/comment", views.post_add_comment, name="post_add_comment"),
    path("post/<str:post_uid>/comment/<str:comment_uid>/reply", views.post_add_reply, name="post_add_reply"),
    path("comment/<str:comment_uid>/like", views.comment_like_toggle, name="comment_like_toggle"),
]

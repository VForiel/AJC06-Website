from django.urls import path

from . import views

app_name = "blog"

urlpatterns = [
    path("", views.post_list, name="list"),
    path("rss/", views.LatestPosts(), name="rss"),
    path("<slug:slug>/", views.post_detail, name="detail"),
]

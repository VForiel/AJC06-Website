from django.contrib import admin

from .models import Post


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ["title", "status", "published_at", "author"]
    list_filter = ["status"]
    search_fields = ["title", "body"]
    date_hierarchy = "published_at"
    prepopulated_fields = {"slug": ["title"]}

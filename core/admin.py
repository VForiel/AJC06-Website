from django.contrib import admin

from .models import Announcement, Ban, Board, ContactMessage, LoginFailure, Member, Resource, Upload


class MemberInline(admin.TabularInline):
    model = Member
    extra = 1
    fields = ["order", "name", "role", "role_en", "about", "about_en", "photo", "linkedin"]


@admin.register(Board)
class BoardAdmin(admin.ModelAdmin):
    inlines = [MemberInline]


@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ["title", "category", "order"]
    list_filter = ["category"]
    list_editable = ["order"]
    prepopulated_fields = {"slug": ["title"]}
    search_fields = ["title", "body"]


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ["created_at", "name", "email", "subject", "handled"]
    list_filter = ["handled", "subject"]
    search_fields = ["name", "email", "message"]


admin.site.register(Upload)


@admin.register(Ban)
class BanAdmin(admin.ModelAdmin):
    list_display = ["ip", "until", "reason", "created_at"]
    search_fields = ["ip"]


@admin.register(LoginFailure)
class LoginFailureAdmin(admin.ModelAdmin):
    list_display = ["created_at", "ip", "username"]
    search_fields = ["ip", "username"]


admin.site.register(Announcement)

from django.contrib import admin

from .models import Attendance, Friendship, Notification, Profile, Report


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ["display_name", "handle", "doctoral_school", "discipline", "visibility", "created_at"]
    list_filter = ["doctoral_school", "visibility"]
    search_fields = ["display_name", "handle", "user__email", "discipline", "lab"]
    raw_id_fields = ["user"]


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ["created_at", "target", "reporter", "handled"]
    list_filter = ["handled"]


admin.site.register(Friendship)
admin.site.register(Attendance)
admin.site.register(Notification)

from django.contrib import admin

from .models import Event


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["title", "start_date", "types", "venue", "is_published", "on_hold", "is_community"]
    list_filter = ["is_published", "on_hold", "is_community", "supported"]
    search_fields = ["title", "venue", "body"]
    date_hierarchy = "start_date"
    prepopulated_fields = {"slug": ["title"]}

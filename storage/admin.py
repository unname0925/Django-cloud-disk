from django.contrib import admin

from .models import StoredFile, UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "folder_uuid", "created_time")
    search_fields = ("user__username", "folder_uuid")


@admin.register(StoredFile)
class StoredFileAdmin(admin.ModelAdmin):
    list_display = ("original_name", "owner", "file_size", "uploaded_time")
    search_fields = ("original_name", "owner__username")
    list_filter = ("uploaded_time",)
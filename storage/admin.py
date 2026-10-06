from django.contrib import admin
from django.template.defaultfilters import filesizeformat

from .models import Folder, ShareLink, StoredFile, UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "used", "quota_display", "created_time")
    search_fields = ("user__username", "folder_uuid")
    readonly_fields = ("folder_uuid",)

    @admin.display(description="已使用")
    def used(self, obj):
        return filesizeformat(obj.used_bytes)

    @admin.display(description="容量")
    def quota_display(self, obj):
        return filesizeformat(obj.quota)


@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "parent", "created_time")
    search_fields = ("name", "owner__username")
    list_select_related = ("owner", "parent")


@admin.register(StoredFile)
class StoredFileAdmin(admin.ModelAdmin):
    list_display = ("original_name", "owner", "folder", "file_size", "uploaded_time")
    search_fields = ("original_name", "owner__username")
    list_filter = ("uploaded_time",)
    list_select_related = ("owner", "folder")


@admin.register(ShareLink)
class ShareLinkAdmin(admin.ModelAdmin):
    list_display = ("file", "created_time", "expires_time", "download_count")
    readonly_fields = ("token", "download_count")
    list_select_related = ("file",)

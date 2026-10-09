from django.contrib import admin, messages
from django.template.defaultfilters import filesizeformat

from .models import ActivityLog, Folder, ShareLink, StoredFile, UserProfile
from .services import twofactor


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "used", "quota_display", "totp_enabled", "created_time")
    list_filter = ("totp_enabled",)
    search_fields = ("user__username", "folder_uuid")
    readonly_fields = ("folder_uuid", "totp_enabled")
    exclude = ("totp_secret", "totp_last_step")
    actions = ["reset_two_factor"]

    @admin.display(description="已使用")
    def used(self, obj):
        return filesizeformat(obj.used_bytes)

    @admin.display(description="容量")
    def quota_display(self, obj):
        return filesizeformat(obj.quota)

    @admin.action(description="重設兩步驟驗證（使用者遺失手機與備用碼時使用）")
    def reset_two_factor(self, request, queryset):
        for profile in queryset:
            twofactor.disable(profile.user)
        self.message_user(request, f"已重設 {queryset.count()} 位使用者的兩步驟驗證",
                          messages.SUCCESS)


@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "parent", "created_time", "deleted_time")
    search_fields = ("name", "owner__username")
    list_select_related = ("owner", "parent")


@admin.register(StoredFile)
class StoredFileAdmin(admin.ModelAdmin):
    list_display = ("original_name", "owner", "folder", "file_size", "uploaded_time",
                    "deleted_time")
    search_fields = ("original_name", "owner__username", "sha256")
    list_filter = ("uploaded_time",)
    list_select_related = ("owner", "folder")
    readonly_fields = ("sha256",)


@admin.register(ShareLink)
class ShareLinkAdmin(admin.ModelAdmin):
    list_display = ("__str__", "owner", "created_time", "expires_time", "download_count",
                    "max_downloads")
    readonly_fields = ("token", "download_count", "password_hash")
    list_select_related = ("owner", "file", "folder")


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("created_time", "username", "action", "target", "ip", "device")
    list_filter = ("action", "created_time")
    search_fields = ("username", "target", "ip")
    date_hierarchy = "created_time"

    # 紀錄只能查看，不能修改
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

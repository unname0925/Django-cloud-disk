from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import StoredFile, UserProfile
from .services.thumbnails import delete_thumbnail


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)


@receiver(post_delete, sender=StoredFile)
def delete_file_from_disk(sender, instance, **kwargs):
    """刪除資料庫紀錄後一併移除實體檔案。

    用 signal 而不是覆寫 Model.delete()，是因為刪除資料夾或使用者時的連帶刪除
    （cascade）不會呼叫 Model.delete()，實體檔案會殘留在硬碟上。
    等交易確定提交後才刪檔，避免交易回滾時檔案已經不見。
    """
    name = instance.file.name
    if not name:
        return
    storage = instance.file.storage

    def remove_files():
        storage.delete(name)
        delete_thumbnail(storage, name)

    transaction.on_commit(remove_files)

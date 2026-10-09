from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import FileVersion, StoredFile, UserProfile, physical_file_in_use
from .services.thumbnails import delete_thumbnail


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)


def schedule_physical_cleanup(storage, name):
    """交易提交後，若沒有任何紀錄再使用這個實體檔案，就連同縮圖一起刪除。

    等交易確定提交後才刪檔，避免交易回滾時檔案已經不見。
    內容相同的檔案與舊版本會共用實體檔案，所以要先確認沒有人在用。
    """
    if not name:
        return

    def remove_files():
        if physical_file_in_use(name):
            return
        storage.delete(name)
        delete_thumbnail(storage, name)

    transaction.on_commit(remove_files)


@receiver(post_delete, sender=StoredFile)
@receiver(post_delete, sender=FileVersion)
def delete_file_from_disk(sender, instance, **kwargs):
    """刪除資料庫紀錄後一併移除實體檔案。

    用 signal 而不是覆寫 Model.delete()，是因為刪除資料夾或使用者時的連帶刪除
    （cascade）不會呼叫 Model.delete()，實體檔案會殘留在硬碟上。
    """
    schedule_physical_cleanup(instance.file.storage, instance.file.name)

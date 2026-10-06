from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from storage.models import UploadSession, upload_temp_dir
from storage.services import trash, uploads


class Command(BaseCommand):
    help = "永久刪除超過保留期限的回收筒項目，並清除逾時未完成的分段上傳"

    def handle(self, *args, **options):
        purged = trash.purge_expired()

        cutoff = timezone.now() - timedelta(hours=settings.STORAGE_UPLOAD_SESSION_HOURS)
        stale = list(UploadSession.objects.filter(updated_time__lt=cutoff))
        for session in stale:
            uploads.cancel(session)

        # 清除沒有對應 session 的暫存檔（例如資料庫被還原過）
        orphans = 0
        temp_dir = upload_temp_dir()
        if temp_dir.exists():
            known = {f"{pk}.part" for pk in UploadSession.objects.values_list("pk", flat=True)}
            for part in temp_dir.glob("*.part"):
                too_old = part.stat().st_mtime < cutoff.timestamp()
                if part.name not in known and too_old:
                    part.unlink(missing_ok=True)
                    orphans += 1

        self.stdout.write(
            f"回收筒永久刪除 {purged} 個檔案；清除 {len(stale)} 個逾時上傳、{orphans} 個孤立暫存檔"
        )

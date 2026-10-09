from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from storage.services import backup


class Command(BaseCommand):
    help = "從備份檔還原資料庫與使用者檔案（請先停止伺服器）"

    def add_arguments(self, parser):
        parser.add_argument("archive", help="backup 指令產生的 .tar.gz")
        parser.add_argument("--yes", action="store_true", help="不詢問直接還原")

    def handle(self, *args, **options):
        archive = options["archive"]
        try:
            manifest = backup.read_manifest(archive)
        except (backup.BackupError, OSError) as error:
            raise CommandError(str(error))

        self.stdout.write(
            f"備份時間：{manifest['created']}，包含 {manifest['files']} 個檔案。\n"
            "目前的資料庫與檔案會被取代（原本的資料會改名保留，不會刪除）。"
        )
        if not options["yes"] and input("確定要還原嗎？輸入 yes 繼續：").strip() != "yes":
            raise CommandError("已取消")

        try:
            _, kept = backup.restore_backup(archive)
        except backup.BackupError as error:
            raise CommandError(str(error))
        for path in kept:
            self.stdout.write(f"原本的資料保留在：{path}")

        # 備份可能來自較舊的版本，套用新的資料庫結構
        call_command("migrate", interactive=False, verbosity=0)
        self.stdout.write(self.style.SUCCESS("還原完成，請重新啟動伺服器"))

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.template.defaultfilters import filesizeformat

from storage.services import backup


class Command(BaseCommand):
    help = "備份資料庫與使用者檔案成一個 .tar.gz"

    def add_arguments(self, parser):
        parser.add_argument("--output-dir", default=settings.BACKUP_DIR,
                            help=f"備份檔存放位置（預設 {settings.BACKUP_DIR}）")
        parser.add_argument("--keep", type=int, default=settings.BACKUP_KEEP,
                            help="只保留最新的幾份備份，0 代表全部保留")
        parser.add_argument("--no-files", action="store_true", help="只備份資料庫")

    def handle(self, *args, **options):
        try:
            path = backup.create_backup(options["output_dir"],
                                        include_files=not options["no_files"])
        except backup.BackupError as error:
            raise CommandError(str(error))
        self.stdout.write(f"已建立備份：{path}（{filesizeformat(path.stat().st_size)}）")
        for removed in backup.prune_backups(options["output_dir"], options["keep"]):
            self.stdout.write(f"已刪除舊備份：{removed.name}")

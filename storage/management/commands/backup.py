import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.template.defaultfilters import filesizeformat

from storage.services import backup


class Command(BaseCommand):
    help = "備份資料庫與使用者檔案成一個 .tar.gz，並可複製到外接硬碟或雲端空間"

    def add_arguments(self, parser):
        parser.add_argument("--output-dir", default=settings.BACKUP_DIR,
                            help=f"備份檔存放位置（預設 {settings.BACKUP_DIR}）")
        parser.add_argument("--keep", type=int, default=settings.BACKUP_KEEP,
                            help="只保留最新的幾份備份，0 代表全部保留")
        parser.add_argument("--no-files", action="store_true", help="只備份資料庫")
        parser.add_argument("--if-older-than", type=float, metavar="HOURS",
                            help="最近一次備份在這麼多小時內時就不備份（容器啟動時使用）")
        parser.add_argument("--copy-dir", default=settings.BACKUP_COPY_DIR,
                            help="另外複製一份到這個目錄（外接硬碟、NAS）")
        parser.add_argument("--rclone-remote", default=settings.BACKUP_RCLONE_REMOTE,
                            help="另外用 rclone 上傳到這個位置，例如 gdrive:cloud-disk-backups")
        parser.add_argument("--offsite-keep", type=int, default=settings.BACKUP_OFFSITE_KEEP,
                            help="異地備份保留幾份")

    def handle(self, *args, **options):
        output_dir = options["output_dir"]
        if options["if_older_than"] is not None:
            latest = backup.latest_backup(output_dir)
            if latest is not None:
                age_hours = (time.time() - latest.stat().st_mtime) / 3600
                if age_hours < options["if_older_than"]:
                    self.stdout.write(f"最近的備份在 {age_hours:.1f} 小時前，略過")
                    return

        try:
            path = backup.create_backup(output_dir, include_files=not options["no_files"])
            # 先確認備份可以還原，避免把壞掉的備份複製出去
            backup.verify_backup(path)
        except backup.BackupError as error:
            raise CommandError(str(error))
        self.stdout.write(f"已建立並驗證備份：{path}（{filesizeformat(path.stat().st_size)}）")
        for removed in backup.prune_backups(output_dir, options["keep"]):
            self.stdout.write(f"已刪除舊備份：{removed.name}")

        destinations, errors = [], []
        keep = options["offsite_keep"]
        if options["copy_dir"]:
            try:
                removed = backup.copy_to_directory(path, options["copy_dir"], keep)
                destinations.append(str(options["copy_dir"]))
                self.stdout.write(f"已複製到：{options['copy_dir']}")
                for name in removed:
                    self.stdout.write(f"已刪除異地的舊備份：{name}")
            except OSError as error:
                errors.append(f"複製到 {options['copy_dir']} 失敗：{error}")
        if options["rclone_remote"]:
            try:
                removed = backup.copy_to_rclone(path, options["rclone_remote"], keep)
                destinations.append(options["rclone_remote"])
                self.stdout.write(f"已上傳到：{options['rclone_remote']}")
                for name in removed:
                    self.stdout.write(f"已刪除雲端的舊備份：{name}")
            except backup.BackupError as error:
                errors.append(str(error))

        if destinations and not errors:
            backup.record_offsite_success(output_dir, destinations)
        if errors:
            # 本機備份已完成，但異地備份失敗時要讓排程或監控知道
            raise CommandError("；".join(errors))

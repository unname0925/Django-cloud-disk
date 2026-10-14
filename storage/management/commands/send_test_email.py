from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "寄一封測試信，確認 SMTP 設定正確"

    def add_arguments(self, parser):
        parser.add_argument("to", help="收件人 Email")

    def handle(self, *args, **options):
        try:
            send_mail("[Cloud Drive] 測試信", "收到這封信代表寄信設定正確。", None,
                      [options["to"]])
        except Exception as error:  # noqa: BLE001 - 把 SMTP 錯誤原樣回報給使用者
            raise CommandError(f"寄信失敗：{error.__class__.__name__}: {error}")
        self.stdout.write(f"已透過 {settings.EMAIL_HOST or settings.EMAIL_BACKEND} 寄出測試信到 {options['to']}")

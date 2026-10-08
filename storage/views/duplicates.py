from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from ..services import dedupe

# 每次開啟頁面最多補算幾個舊檔案的雜湊，避免檔案很多時頁面卡太久
BACKFILL_LIMIT = 200


@login_required
def duplicates(request):
    processed, merged, remaining = dedupe.backfill(request.user, limit=BACKFILL_LIMIT)
    if merged:
        messages.info(request, f"已合併 {merged} 個內容相同的舊檔案，釋出重複佔用的空間")

    context = {"groups": dedupe.duplicate_groups(request.user), "remaining": remaining}
    return render(request, "storage/duplicates.html", context)

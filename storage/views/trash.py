from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..models import Folder, StoredFile
from ..services import trash


def _trashed_file(request, file_id):
    return get_object_or_404(StoredFile.objects.trashed(), pk=file_id, owner=request.user)


def _trashed_folder(request, folder_id):
    return get_object_or_404(Folder.objects.trashed(), pk=folder_id, owner=request.user)


@login_required
def trash_list(request):
    # 沒有排程時也能清除過期項目：每次打開回收筒都先清一次
    trash.purge_expired(request.user)
    folders, files = trash.trash_roots(request.user)
    context = {
        "folders": [(f, trash.expires_at(f.deleted_time)) for f in folders],
        "files": [(f, trash.expires_at(f.deleted_time)) for f in files],
        "retention_days": settings.STORAGE_TRASH_RETENTION_DAYS,
    }
    return render(request, "storage/trash.html", context)


@login_required
@require_POST
def restore_file(request, file_id):
    stored = _trashed_file(request, file_id)
    trash.restore_file(stored)
    messages.success(request, f"已還原「{stored.original_name}」")
    return redirect("storage:trash")


@login_required
@require_POST
def restore_folder(request, folder_id):
    folder = _trashed_folder(request, folder_id)
    trash.restore_folder(folder)
    messages.success(request, f"已還原資料夾「{folder.name}」")
    return redirect("storage:trash")


@login_required
@require_POST
def purge_file(request, file_id):
    stored = _trashed_file(request, file_id)
    stored.delete()
    messages.success(request, f"已永久刪除「{stored.original_name}」")
    return redirect("storage:trash")


@login_required
@require_POST
def purge_folder(request, folder_id):
    folder = _trashed_folder(request, folder_id)
    folder.delete()
    messages.success(request, f"已永久刪除資料夾「{folder.name}」")
    return redirect("storage:trash")


@login_required
@require_POST
def empty_trash(request):
    count = trash.empty_trash(request.user)
    messages.success(request, f"已清空資源回收筒（{count} 個檔案）")
    return redirect("storage:trash")

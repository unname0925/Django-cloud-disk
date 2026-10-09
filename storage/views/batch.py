from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from ..models import Folder
from ..services import batch
from ..services.archive import build_selection_zip


def _ids(request, name):
    return [int(value) for value in request.POST.getlist(name) if value.isdigit()]


def _back(request):
    next_url = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect("storage:browse")


@login_required
@require_POST
def batch_action(request):
    folders, files = batch.selected_items(
        request.user, _ids(request, "file"), _ids(request, "folder")
    )
    if not folders and not files:
        messages.error(request, "請先勾選要處理的檔案或資料夾")
        return _back(request)

    action = request.POST.get("action")
    count = len(folders) + len(files)

    if action == "zip":
        archive, filename = build_selection_zip(request.user, folders, files)
        return FileResponse(archive, as_attachment=True, filename=filename,
                            content_type="application/zip")

    if action == "trash":
        batch.trash_items(folders, files)
        messages.success(request, f"已將 {count} 個項目移到資源回收筒")
        return _back(request)

    if action == "move":
        target_id = request.POST.get("target", "")
        target = (
            get_object_or_404(Folder.objects.active(), pk=target_id, owner=request.user)
            if target_id.isdigit() else None
        )
        errors = batch.move_items(folders, files, target)
        for error in errors:
            messages.error(request, error)
        moved = count - len(errors)
        if moved:
            messages.success(request, f"已移動 {moved} 個項目到「{target.name if target else '根目錄'}」")
        return _back(request)

    messages.error(request, "不支援的操作")
    return _back(request)

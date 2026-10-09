from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..models import FileVersion
from ..services import versions
from .common import get_owned_file, serve_file


def _owned_version(request, version_id):
    return get_object_or_404(
        FileVersion.objects.select_related("stored_file"),
        pk=version_id,
        stored_file__owner=request.user,
        stored_file__deleted_time__isnull=True,
    )


@login_required
def file_versions(request, file_id):
    stored = get_owned_file(request, file_id)
    context = {"file": stored, "versions": stored.versions.all()}
    return render(request, "storage/versions.html", context)


@login_required
def download_version(request, version_id):
    version = _owned_version(request, version_id)
    stored = version.stored_file
    return serve_file(
        request,
        version.file,
        filename=stored.original_name,
        content_type=stored.content_type,
        as_attachment=True,
    )


@login_required
@require_POST
def restore_version(request, version_id):
    version = _owned_version(request, version_id)
    stored = version.stored_file
    versions.restore(version)
    messages.success(request, f"已還原「{stored.original_name}」的舊版本，原本的內容保存為一個版本")
    return redirect("storage:file_versions", file_id=stored.pk)


@login_required
@require_POST
def delete_version(request, version_id):
    version = _owned_version(request, version_id)
    file_id = version.stored_file_id
    version.delete()
    messages.success(request, "已刪除這個版本")
    return redirect("storage:file_versions", file_id=file_id)

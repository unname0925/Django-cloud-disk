from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect

from ..models import Folder, StoredFile


def client_ip(request):
    if settings.TRUST_PROXY_HEADERS:
        # 反向代理會把真實 IP 附加在 X-Forwarded-For 最後面
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR", "")


def get_owned_folder(request, folder_id):
    return get_object_or_404(Folder.objects.active(), pk=folder_id, owner=request.user)


def get_owned_file(request, file_id):
    return get_object_or_404(StoredFile.objects.active(), pk=file_id, owner=request.user)


def redirect_to_folder(folder):
    if folder is None:
        return redirect("storage:browse")
    return redirect("storage:browse_folder", folder_id=folder.pk)


def file_response(stored_file, *, as_attachment):
    try:
        handle = stored_file.file.open("rb")
    except FileNotFoundError:
        raise Http404("檔案不存在")

    content_type = stored_file.content_type
    if content_type.startswith("text/"):
        content_type += "; charset=utf-8"

    return FileResponse(
        handle,
        as_attachment=as_attachment,
        filename=stored_file.original_name,
        content_type=content_type,
    )

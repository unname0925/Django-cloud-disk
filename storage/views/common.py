from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect

from ..models import Folder, StoredFile


def get_owned_folder(request, folder_id):
    return get_object_or_404(Folder, pk=folder_id, owner=request.user)


def get_owned_file(request, file_id):
    return get_object_or_404(StoredFile, pk=file_id, owner=request.user)


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

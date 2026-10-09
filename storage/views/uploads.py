"""分段上傳的 JSON API，供拖曳上傳的前端程式使用。"""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods, require_POST

from ..forms import ChunkedUploadStartForm, ChunkForm
from ..models import UploadSession
from ..services import uploads


def _session_json(session, result=None):
    data = {
        "id": str(session.pk),
        "received_bytes": session.total_size if result else session.received_bytes,
        "total_size": session.total_size,
        "chunk_size": settings.STORAGE_CHUNK_SIZE,
        "done": result is not None,
    }
    if result is not None:
        data["file_id"] = result.stored.pk
        data["outcome"] = result.outcome
    return data


def _note_result(request, result):
    # 訊息會在上傳完成、前端重新整理頁面後顯示
    if result is not None and result.message():
        messages.info(request, result.message())


def _form_error(form):
    message = "; ".join(e for errors in form.errors.values() for e in errors)
    return JsonResponse({"error": message}, status=400)


@login_required
@require_POST
def start_upload(request):
    form = ChunkedUploadStartForm(request.POST, user=request.user)
    if not form.is_valid():
        return _form_error(form)
    try:
        session, result = uploads.start_session(
            request.user,
            form.cleaned_data["name"],
            form.cleaned_data["size"],
            form.cleaned_data["folder"],
        )
    except uploads.UploadError as error:
        return JsonResponse({"error": error.message}, status=error.status)
    _note_result(request, result)
    return JsonResponse(_session_json(session, result), status=201)


@login_required
@require_http_methods(["GET", "POST"])
def upload_session(request, session_id):
    session = get_object_or_404(UploadSession, pk=session_id, owner=request.user)
    if request.method == "GET":
        return JsonResponse(_session_json(session))

    form = ChunkForm(request.POST, request.FILES)
    if not form.is_valid():
        return _form_error(form)
    try:
        session, result = uploads.append_chunk(
            session, form.cleaned_data["offset"], form.cleaned_data["chunk"]
        )
    except uploads.UploadError as error:
        if error.status == 409:
            # 前端依照回傳的 received_bytes 從正確位置繼續
            session.refresh_from_db()
            return JsonResponse({**_session_json(session), "error": error.message}, status=409)
        return JsonResponse({"error": error.message}, status=error.status)
    except UploadSession.DoesNotExist:
        return JsonResponse({"error": "上傳已取消"}, status=404)
    _note_result(request, result)
    return JsonResponse(_session_json(session, result))


@login_required
@require_POST
def cancel_upload(request, session_id):
    session = get_object_or_404(UploadSession, pk=session_id, owner=request.user)
    uploads.cancel(session)
    return JsonResponse({"cancelled": True})

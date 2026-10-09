import re

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.http import content_disposition_header

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


RANGE_PATTERN = re.compile(r"^bytes=(\d*)-(\d*)$")
STREAM_BLOCK = 64 * 1024


class RangeNotSatisfiable(Exception):
    pass


def parse_range(header, size):
    """解析單一範圍的 Range 標頭，回傳 (start, end)；無法使用時回傳 None 改傳整個檔案。"""
    match = RANGE_PATTERN.match(header.strip())
    if not match:
        return None  # 格式不符或多重範圍：依規範可以忽略，回傳完整內容
    first, last = match.groups()
    if not first and not last:
        return None
    if not first:
        # bytes=-500 代表最後 500 個位元組
        length = int(last)
        if length == 0 or size == 0:
            raise RangeNotSatisfiable
        return max(size - length, 0), size - 1
    start = int(first)
    if start >= size:
        raise RangeNotSatisfiable
    end = min(int(last), size - 1) if last else size - 1
    if end < start:
        return None
    return start, end


def is_initial_request(request):
    """不是從頭開始的 Range 請求（影片拖曳、下載續傳）不算一次新的下載。"""
    header = request.headers.get("Range", "")
    if not header or request.headers.get("If-Range"):
        return True  # 會回傳完整內容
    match = RANGE_PATTERN.match(header.strip())
    if not match:
        return True  # 格式不符時同樣回傳完整內容
    return match.group(1) == "0"


def _stream(handle, start, length):
    try:
        handle.seek(start)
        remaining = length
        while remaining > 0:
            block = handle.read(min(STREAM_BLOCK, remaining))
            if not block:
                break
            remaining -= len(block)
            yield block
    finally:
        handle.close()


def serve_file(request, field_file, *, filename, content_type, as_attachment):
    """回傳檔案內容，支援 HTTP Range（影片拖曳進度條、下載續傳）。"""
    try:
        size = field_file.size
        handle = field_file.storage.open(field_file.name, "rb")
    except FileNotFoundError:
        raise Http404("檔案不存在")

    if content_type.startswith("text/"):
        content_type += "; charset=utf-8"

    byte_range = None
    # 帶有 If-Range 時無法確認快取的版本，保守地回傳完整內容
    if request.headers.get("Range") and not request.headers.get("If-Range"):
        try:
            byte_range = parse_range(request.headers["Range"], size)
        except RangeNotSatisfiable:
            handle.close()
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{size}"
            return response

    if byte_range is None:
        response = FileResponse(
            handle, as_attachment=as_attachment, filename=filename, content_type=content_type
        )
    else:
        start, end = byte_range
        length = end - start + 1
        response = StreamingHttpResponse(
            _stream(handle, start, length), status=206, content_type=content_type
        )
        response["Content-Length"] = str(length)
        response["Content-Range"] = f"bytes {start}-{end}/{size}"
        response["Content-Disposition"] = content_disposition_header(as_attachment, filename)
    response["Accept-Ranges"] = "bytes"
    return response


def file_response(request, stored_file, *, as_attachment):
    return serve_file(
        request,
        stored_file.file,
        filename=stored_file.original_name,
        content_type=stored_file.content_type,
        as_attachment=as_attachment,
    )

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.shortcuts import render

from ..models import Folder, StoredFile, UserProfile
from ..services import batch
from .common import get_owned_folder

SORT_FIELDS = {
    "name": "original_name",
    "-name": "-original_name",
    "size": "file_size",
    "-size": "-file_size",
    "time": "uploaded_time",
    "-time": "-uploaded_time",
}
DEFAULT_SORT = "-time"


VIEW_MODES = ("list", "grid")


@login_required
def browse(request, folder_id=None):
    folder = get_owned_folder(request, folder_id) if folder_id else None

    # 記住使用者選擇的檢視模式（列表／相簿）
    view_mode = request.GET.get("view")
    if view_mode in VIEW_MODES:
        request.session["view_mode"] = view_mode
    else:
        view_mode = request.session.get("view_mode", "list")

    query = request.GET.get("q", "").strip()
    sort = request.GET.get("sort", DEFAULT_SORT)
    if sort not in SORT_FIELDS:
        sort = DEFAULT_SORT

    files = StoredFile.objects.active().filter(owner=request.user)
    folders = Folder.objects.active().filter(owner=request.user)
    if query:
        # 搜尋時涵蓋所有資料夾
        files = files.filter(original_name__icontains=query).select_related("folder")
        folders = folders.filter(name__icontains=query).select_related("parent")
    else:
        files = files.filter(folder=folder)
        folders = folders.filter(parent=folder)

    profile = UserProfile.for_user(request.user)
    used, quota = profile.used_bytes, profile.quota
    usage_percent = min(100, round(used * 100 / quota)) if quota else 100

    context = {
        "folder": folder,
        "breadcrumbs": folder.ancestors() if folder else [],
        "folders": folders,
        "files": files.annotate(version_count=Count("versions")).order_by(SORT_FIELDS[sort]),
        "query": query,
        "sort": sort,
        "used_bytes": used,
        "quota_bytes": quota,
        "usage_percent": usage_percent,
        "trash_bytes": StoredFile.objects.trashed().filter(owner=request.user)
        .aggregate(total=Sum("file_size"))["total"] or 0,
        "view_mode": view_mode,
        "move_targets": batch.folder_choices(request.user) if view_mode == "list" else [],
        "chunk_size": settings.STORAGE_CHUNK_SIZE,
    }
    return render(request, "storage/browse.html", context)

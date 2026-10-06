from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from ..models import Folder, StoredFile, UserProfile
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


@login_required
def browse(request, folder_id=None):
    folder = get_owned_folder(request, folder_id) if folder_id else None
    query = request.GET.get("q", "").strip()
    sort = request.GET.get("sort", DEFAULT_SORT)
    if sort not in SORT_FIELDS:
        sort = DEFAULT_SORT

    files = StoredFile.objects.filter(owner=request.user)
    folders = Folder.objects.filter(owner=request.user)
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
        "files": files.order_by(SORT_FIELDS[sort]),
        "query": query,
        "sort": sort,
        "used_bytes": used,
        "quota_bytes": quota,
        "usage_percent": usage_percent,
    }
    return render(request, "storage/browse.html", context)

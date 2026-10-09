from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from ..forms import SharePasswordForm, ShareLinkForm
from ..models import ActivityLog, Folder, ShareLink, StoredFile
from ..services import activity, shares
from ..services.archive import build_zip
from .common import (
    client_ip,
    file_response,
    get_owned_file,
    get_owned_folder,
    is_initial_request,
)

# --- 擁有者管理分享連結 -----------------------------------------------------


def _link_rows(request, links):
    return [
        (link, request.build_absolute_uri(reverse("storage:shared_file", args=[link.token])))
        for link in links
    ]


@login_required
def manage_shares(request, file_id=None, folder_id=None):
    if file_id is not None:
        target = get_owned_file(request, file_id)
        target_kwargs = {"file": target}
        target_name, parent_folder = target.original_name, target.folder
    else:
        target = get_owned_folder(request, folder_id)
        target_kwargs = {"folder": target}
        target_name, parent_folder = target.name, target.parent

    form = ShareLinkForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        link = shares.create_link(
            request.user,
            expires_time=form.expires_time(),
            password=form.cleaned_data["password"],
            max_downloads=form.cleaned_data["max_downloads"],
            **target_kwargs,
        )
        activity.record(request, ActivityLog.Action.SHARE_CREATE, target=link.target_name)
        messages.success(request, "已建立分享連結")
        return redirect(request.path)

    links = ShareLink.objects.filter(owner=request.user, **target_kwargs)
    context = {
        "form": form,
        "target_name": target_name,
        "is_folder": folder_id is not None,
        "cancel_folder": parent_folder,
        "links": _link_rows(request, links),
    }
    return render(request, "storage/shares.html", context)


@login_required
def my_shares(request):
    links = ShareLink.objects.filter(owner=request.user).select_related("file", "folder")
    return render(request, "storage/my_shares.html", {"links": _link_rows(request, links)})


@login_required
@require_POST
def revoke_share(request, link_id):
    link = get_object_or_404(ShareLink, pk=link_id, owner=request.user)
    activity.record(request, ActivityLog.Action.SHARE_REVOKE, target=link.target_name)
    link.delete()
    messages.success(request, "分享連結已撤銷")
    next_url = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect("storage:my_shares")


# --- 公開的分享頁面（不需登入） ---------------------------------------------


def _unavailable(request, link):
    return render(request, "storage/shared_unavailable.html", {"link": link}, status=410)


def _load_link(request, token, item=None):
    """回傳 (連結, 要直接回傳的 response)。連結失效或需要密碼時會回傳對應頁面。

    item 是要下載的項目；已達下載次數上限時，仍允許同一位訪客續傳先前開始下載的項目。
    """
    link = get_object_or_404(
        ShareLink.objects.select_related("file", "folder", "owner"), token=token
    )
    continuing = (
        item is not None
        and not is_initial_request(request)
        and shares.has_continuation(request, link, item)
    )
    only_exhausted = link.is_exhausted and not link.is_expired and not link.target_in_trash
    if not link.is_active and not (continuing and only_exhausted):
        return link, _unavailable(request, link)
    if not shares.is_unlocked(request, link):
        return link, redirect("storage:shared_file", token=token)
    return link, None


def shared_file(request, token):
    """分享連結的入口：檔案顯示下載頁，資料夾顯示內容列表。"""
    link = get_object_or_404(
        ShareLink.objects.select_related("file", "folder", "owner"), token=token
    )
    if not link.is_active:
        return _unavailable(request, link)

    if not shares.is_unlocked(request, link):
        ip = client_ip(request)
        form = SharePasswordForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            if shares.try_unlock(request, link, form.cleaned_data["password"], ip):
                return redirect(request.path)
            form.add_error("password", "密碼不正確")
        locked = shares.is_password_locked(link, ip)
        return render(request, "storage/shared_password.html",
                      {"form": form, "locked": locked}, status=429 if locked else 200)

    if link.file_id:
        return render(request, "storage/shared_file.html", {"link": link, "file": link.file})
    return _render_shared_folder(request, link, link.folder)


def shared_subfolder(request, token, folder_id):
    link, response = _load_link(request, token)
    if response is not None:
        return response
    if not link.folder_id:
        return redirect("storage:shared_file", token=token)
    return _render_shared_folder(request, link, shares.shared_folder(link, folder_id))


def _render_shared_folder(request, link, folder):
    context = {
        "link": link,
        "folder": folder,
        "breadcrumbs": shares.breadcrumbs(link, folder),
        "folders": Folder.objects.active().filter(parent=folder),
        "files": StoredFile.objects.active().filter(folder=folder).order_by("original_name"),
    }
    return render(request, "storage/shared_folder.html", context)


def _count_download(request, link, item):
    """需要計算一次下載時登記；回傳 False 表示已達上限。

    從頭開始的請求算一次新的下載；續傳只有在同一位訪客先前開始過這個項目時才不計算，
    否則可以用多個 Range 請求拼出完整檔案來繞過次數限制。
    """
    if not is_initial_request(request) and shares.has_continuation(request, link, item):
        return True
    if not shares.register_download(link):
        return False
    shares.grant_continuation(request, link, item)
    # 記在分享者的紀錄裡，讓分享者知道連結被誰下載
    activity.record(request, ActivityLog.Action.SHARE_DOWNLOAD, user=link.owner,
                    target=link.target_name)
    return True


def shared_download(request, token):
    """下載分享的檔案；分享資料夾時下載整個資料夾的 zip。"""
    link, response = _load_link(request, token, item="main")
    if response is not None:
        return response
    if not _count_download(request, link, "main"):
        return _unavailable(request, link)
    if link.file_id:
        return file_response(request, link.file, as_attachment=True)
    archive, filename = build_zip(link.owner, link.folder)
    return FileResponse(archive, as_attachment=True, filename=filename,
                        content_type="application/zip")


def shared_folder_file(request, token, file_id):
    link, response = _load_link(request, token, item=f"file:{file_id}")
    if response is not None:
        return response
    if not link.folder_id:
        return redirect("storage:shared_file", token=token)
    stored = shares.shared_folder_file(link, file_id)
    if not _count_download(request, link, f"file:{file_id}"):
        return _unavailable(request, link)
    return file_response(request, stored, as_attachment=True)

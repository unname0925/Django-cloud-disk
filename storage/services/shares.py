"""分享連結：密碼保護、下載次數限制、分享資料夾。"""
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.db.models import F
from django.http import Http404

from ..models import Folder, ShareLink, StoredFile

PASSWORD_MAX_ATTEMPTS = 5


def create_link(owner, *, file=None, folder=None, expires_time=None, password="",
                max_downloads=None):
    return ShareLink.objects.create(
        owner=owner,
        file=file,
        folder=folder,
        expires_time=expires_time,
        password_hash=make_password(password) if password else "",
        max_downloads=max_downloads,
    )


def register_download(link):
    """記錄一次下載；已達次數上限時回傳 False。"""
    links = ShareLink.objects.filter(pk=link.pk)
    if link.max_downloads is not None:
        links = links.filter(download_count__lt=link.max_downloads)
    return bool(links.update(download_count=F("download_count") + 1))


def _session_key(link):
    return f"share-unlocked:{link.pk}"


def is_unlocked(request, link):
    return not link.has_password or request.session.get(_session_key(link)) is True


def _attempt_key(link, ip):
    return f"share-password:{link.pk}:{ip}"


def is_password_locked(link, ip):
    return cache.get(_attempt_key(link, ip), 0) >= PASSWORD_MAX_ATTEMPTS


def try_unlock(request, link, password, ip):
    """密碼正確時解鎖這個連結（記在 session）；同一 IP 錯太多次會暫時鎖定。"""
    if is_password_locked(link, ip):
        return False
    if link.check_password(password):
        request.session[_session_key(link)] = True
        cache.delete(_attempt_key(link, ip))
        return True
    key = _attempt_key(link, ip)
    cache.set(key, cache.get(key, 0) + 1, settings.LOGIN_LOCKOUT_SECONDS)
    return False


def shared_folder(link, folder_id=None):
    """取得分享資料夾內的某個資料夾，確保它在分享範圍內而且沒有被刪除。"""
    if folder_id is None:
        return link.folder
    if folder_id not in link.folder.descendant_ids():
        raise Http404
    try:
        return Folder.objects.active().get(pk=folder_id, owner=link.owner)
    except Folder.DoesNotExist:
        raise Http404


def shared_folder_file(link, file_id):
    try:
        stored = StoredFile.objects.active().get(pk=file_id, owner=link.owner)
    except StoredFile.DoesNotExist:
        raise Http404
    if stored.folder_id not in link.folder.descendant_ids():
        raise Http404
    return stored


def breadcrumbs(link, folder):
    """分享根目錄到目前資料夾的路徑（不包含分享範圍以外的上層資料夾）。"""
    chain = folder.ancestors()
    return chain[[f.pk for f in chain].index(link.folder_id):]

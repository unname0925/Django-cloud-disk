from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import F
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..forms import ShareLinkForm
from ..models import ShareLink
from .common import file_response, get_owned_file


@login_required
def manage_shares(request, file_id):
    stored = get_owned_file(request, file_id)
    if request.method == "POST":
        form = ShareLinkForm(request.POST)
        if form.is_valid():
            ShareLink.objects.create(file=stored, expires_time=form.expires_time())
            messages.success(request, "已建立分享連結")
            return redirect("storage:manage_shares", file_id=stored.pk)
    else:
        form = ShareLinkForm()

    links = [
        (link, request.build_absolute_uri(reverse("storage:shared_file", args=[link.token])))
        for link in stored.share_links.all()
    ]
    return render(
        request, "storage/shares.html", {"file": stored, "form": form, "links": links}
    )


@login_required
@require_POST
def revoke_share(request, link_id):
    link = get_object_or_404(ShareLink, pk=link_id, file__owner=request.user)
    file_id = link.file_id
    link.delete()
    messages.success(request, "分享連結已撤銷")
    return redirect("storage:manage_shares", file_id=file_id)


def _get_active_link(token):
    link = get_object_or_404(ShareLink.objects.select_related("file"), token=token)
    if link.is_expired:
        raise Http404("分享連結已過期")
    return link


def shared_file(request, token):
    link = _get_active_link(token)
    return render(request, "storage/shared_file.html", {"link": link, "file": link.file})


def shared_download(request, token):
    link = _get_active_link(token)
    ShareLink.objects.filter(pk=link.pk).update(download_count=F("download_count") + 1)
    return file_response(link.file, as_attachment=True)

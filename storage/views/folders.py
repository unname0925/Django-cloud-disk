from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from ..forms import FolderForm
from ..models import Folder, StoredFile
from .common import get_owned_folder, redirect_to_folder


@login_required
def create_folder(request, parent_id=None):
    parent = get_owned_folder(request, parent_id) if parent_id else None
    form = FolderForm(request.POST or None, user=request.user, parent=parent)
    if request.method == "POST" and form.is_valid():
        Folder.objects.create(owner=request.user, parent=parent, name=form.cleaned_data["name"])
        messages.success(request, "資料夾已建立")
        return redirect_to_folder(parent)

    return render(
        request,
        "storage/form_page.html",
        {"form": form, "title": "新增資料夾", "submit_label": "建立", "cancel_folder": parent},
    )


@login_required
def rename_folder(request, folder_id):
    folder = get_owned_folder(request, folder_id)
    form = FolderForm(
        request.POST or None, user=request.user, parent=folder.parent, instance=folder
    )
    if request.method == "POST" and form.is_valid():
        folder.name = form.cleaned_data["name"]
        folder.save(update_fields=["name"])
        messages.success(request, "資料夾已重新命名")
        return redirect_to_folder(folder.parent)

    return render(
        request,
        "storage/form_page.html",
        {"form": form, "title": f"重新命名「{folder.name}」", "submit_label": "儲存",
         "cancel_folder": folder.parent},
    )


def _descendant_ids(folder):
    ids, frontier = [folder.pk], [folder.pk]
    while frontier:
        frontier = list(
            Folder.objects.filter(parent_id__in=frontier).values_list("pk", flat=True)
        )
        ids.extend(frontier)
    return ids


@login_required
def delete_folder(request, folder_id):
    folder = get_owned_folder(request, folder_id)
    if request.method == "POST":
        parent = folder.parent
        # 子資料夾與檔案會連帶刪除，實體檔案由 post_delete signal 清除
        folder.delete()
        messages.success(request, "資料夾已刪除")
        return redirect_to_folder(parent)

    folder_ids = _descendant_ids(folder)
    context = {
        "name": folder.name,
        "is_folder": True,
        "file_count": StoredFile.objects.filter(folder_id__in=folder_ids).count(),
        "subfolder_count": len(folder_ids) - 1,
        "cancel_folder": folder.parent,
    }
    return render(request, "storage/delete_confirm.html", context)

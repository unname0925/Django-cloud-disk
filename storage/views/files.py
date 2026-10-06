from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from ..forms import MoveFileForm, RenameFileForm, UploadForm
from ..models import Folder, StoredFile
from .common import file_response, get_owned_file, redirect_to_folder


@login_required
def upload(request):
    if request.method == "POST":
        form = UploadForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            folder = form.cleaned_data["folder"]
            files = form.cleaned_data["files"]
            for uploaded in files:
                StoredFile.objects.create(
                    owner=request.user,
                    folder=folder,
                    file=uploaded,
                    original_name=uploaded.name,
                    file_size=uploaded.size,
                )
            messages.success(request, f"已上傳 {len(files)} 個檔案")
            return redirect_to_folder(folder)
    else:
        folder_param = request.GET.get("folder", "")
        initial_folder = (
            Folder.objects.filter(owner=request.user, pk=folder_param).first()
            if folder_param.isdigit()
            else None
        )
        form = UploadForm(user=request.user, initial={"folder": initial_folder})

    return render(request, "storage/upload.html", {"form": form})


@login_required
def download_file(request, file_id):
    return file_response(get_owned_file(request, file_id), as_attachment=True)


@login_required
def preview_file(request, file_id):
    stored = get_owned_file(request, file_id)
    if not stored.is_previewable:
        return redirect("storage:download_file", file_id=stored.pk)
    return file_response(stored, as_attachment=False)


@login_required
def rename_file(request, file_id):
    stored = get_owned_file(request, file_id)
    if request.method == "POST":
        form = RenameFileForm(request.POST)
        if form.is_valid():
            stored.original_name = form.cleaned_data["name"]
            stored.save(update_fields=["original_name"])
            messages.success(request, "檔案已重新命名")
            return redirect_to_folder(stored.folder)
    else:
        form = RenameFileForm(initial={"name": stored.original_name})

    return render(
        request,
        "storage/form_page.html",
        {"form": form, "title": f"重新命名「{stored.original_name}」", "submit_label": "儲存",
         "cancel_folder": stored.folder},
    )


@login_required
def move_file(request, file_id):
    stored = get_owned_file(request, file_id)
    if request.method == "POST":
        form = MoveFileForm(request.POST, user=request.user)
        if form.is_valid():
            stored.folder = form.cleaned_data["folder"]
            stored.save(update_fields=["folder"])
            messages.success(request, "檔案已移動")
            return redirect_to_folder(stored.folder)
    else:
        form = MoveFileForm(user=request.user, initial={"folder": stored.folder})

    return render(
        request,
        "storage/form_page.html",
        {"form": form, "title": f"移動「{stored.original_name}」", "submit_label": "移動",
         "cancel_folder": stored.folder},
    )


@login_required
def delete_file(request, file_id):
    stored = get_owned_file(request, file_id)
    if request.method == "POST":
        folder = stored.folder
        stored.delete()
        messages.success(request, "檔案已刪除")
        return redirect_to_folder(folder)

    return render(
        request,
        "storage/delete_confirm.html",
        {"name": stored.original_name, "cancel_folder": stored.folder},
    )

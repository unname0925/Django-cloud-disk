from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import RegisterForm, UploadForm
from .models import StoredFile


def registerF(request):
    if request.user.is_authenticated:
        
        return redirect("dashboard")

    if request.method == "POST":
        Temp = RegisterForm(request.POST)

        if Temp.is_valid():
            user = Temp.save()
            login(request, user)
            messages.success(request, "註冊成功")

            return redirect("dashboard")
    else:
        Temp = RegisterForm()

    return render(request, "storage/register.html", {"form": Temp})


def loginF(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        Temp = AuthenticationForm(request, data=request.POST)

        if Temp.is_valid():
            user = Temp.get_user()
            login(request, user)
            messages.success(request, "登入成功")

            return redirect("dashboard")
    else:
        Temp = AuthenticationForm()

    return render(request, "storage/login.html", {"form": Temp})



def logoutF(request):
    if request.method == "POST":
        logout(request)

    return redirect("login")



@login_required
def dashboardF(request):
    Temp = StoredFile.objects.filter(owner=request.user).order_by("-uploaded_time")

    return render(request, "storage/dashboard.html", {"files": Temp})



@login_required
def uploadF(request):
    if request.method == "POST":
        Temp = UploadForm(request.POST, request.FILES)
        
        if Temp.is_valid():
            uploaded_file = request.FILES["file"]

            StoredFile.objects.create(
                owner=request.user,
                file=uploaded_file,
                original_name=uploaded_file.name,
                file_size=uploaded_file.size,
            )

            messages.success(request, "上傳成功")

            return redirect("dashboard")
    else:
        Temp = UploadForm()

    return render(request, "storage/upload.html", {"form": Temp})


@login_required
def downloadF(request, file_id):
    Temp = get_object_or_404(StoredFile, id=file_id, owner=request.user)

    return FileResponse(
        Temp.file.open("rb"),
        as_attachment=True,
        filename=Temp.original_name,
    )


@login_required
def deleteF(request, file_id):
    Temp = get_object_or_404(StoredFile, id=file_id, owner=request.user)

    if request.method == "POST":
        Temp.delete()
        messages.success(request, "檔案已刪除")

        return redirect("dashboard")
    return render(request, "storage/delete_confirm.html", {"file": Temp})
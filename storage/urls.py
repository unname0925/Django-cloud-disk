from django.urls import path

from . import views

app_name = "storage"

urlpatterns = [
    # 帳號
    path("register/", views.register, name="register"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    # 瀏覽
    path("", views.browse, name="browse"),
    path("folder/<int:folder_id>/", views.browse, name="browse_folder"),
    # 資料夾
    path("folder/new/", views.create_folder, name="create_folder"),
    path("folder/<int:parent_id>/new/", views.create_folder, name="create_subfolder"),
    path("folder/<int:folder_id>/rename/", views.rename_folder, name="rename_folder"),
    path("folder/<int:folder_id>/delete/", views.delete_folder, name="delete_folder"),
    # 檔案
    path("upload/", views.upload, name="upload"),
    path("file/<int:file_id>/download/", views.download_file, name="download_file"),
    path("file/<int:file_id>/preview/", views.preview_file, name="preview_file"),
    path("file/<int:file_id>/rename/", views.rename_file, name="rename_file"),
    path("file/<int:file_id>/move/", views.move_file, name="move_file"),
    path("file/<int:file_id>/delete/", views.delete_file, name="delete_file"),
    # 分享
    path("file/<int:file_id>/share/", views.manage_shares, name="manage_shares"),
    path("share/<int:link_id>/revoke/", views.revoke_share, name="revoke_share"),
    path("s/<str:token>/", views.shared_file, name="shared_file"),
    path("s/<str:token>/download/", views.shared_download, name="shared_download"),
]

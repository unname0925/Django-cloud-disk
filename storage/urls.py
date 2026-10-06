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
    path("folder/<int:folder_id>/zip/", views.download_folder, name="download_folder"),
    path("zip/", views.download_folder, name="download_all"),
    # 檔案
    path("upload/", views.upload, name="upload"),
    path("upload/sessions/", views.start_upload, name="start_upload"),
    path("upload/sessions/<uuid:session_id>/", views.upload_session, name="upload_session"),
    path("upload/sessions/<uuid:session_id>/cancel/", views.cancel_upload, name="cancel_upload"),
    path("file/<int:file_id>/download/", views.download_file, name="download_file"),
    path("file/<int:file_id>/preview/", views.preview_file, name="preview_file"),
    path("file/<int:file_id>/thumbnail/", views.thumbnail, name="thumbnail"),
    path("file/<int:file_id>/rename/", views.rename_file, name="rename_file"),
    path("file/<int:file_id>/move/", views.move_file, name="move_file"),
    path("file/<int:file_id>/delete/", views.delete_file, name="delete_file"),
    # 資源回收筒
    path("trash/", views.trash_list, name="trash"),
    path("trash/empty/", views.empty_trash, name="empty_trash"),
    path("trash/file/<int:file_id>/restore/", views.restore_file, name="restore_file"),
    path("trash/file/<int:file_id>/purge/", views.purge_file, name="purge_file"),
    path("trash/folder/<int:folder_id>/restore/", views.restore_folder, name="restore_folder"),
    path("trash/folder/<int:folder_id>/purge/", views.purge_folder, name="purge_folder"),
    # 分享
    path("file/<int:file_id>/share/", views.manage_shares, name="manage_shares"),
    path("share/<int:link_id>/revoke/", views.revoke_share, name="revoke_share"),
    path("s/<str:token>/", views.shared_file, name="shared_file"),
    path("s/<str:token>/download/", views.shared_download, name="shared_download"),
]

import uuid
from pathlib import Path

from django.contrib.auth.models import User
from django.db import models
from django.utils.text import get_valid_filename


def upload_to_user(instance, filename):
    Temp= Path(filename).name
    Temp = get_valid_filename(Temp)
    Temp = f"{uuid.uuid4().hex}_{Temp}"
    return f"users/{instance.owner.profile.folder_uuid}/{Temp}"


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    folder_uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} profile"


class StoredFile(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="stored_files")
    file = models.FileField(upload_to=upload_to_user)
    original_name = models.CharField(max_length=255)
    file_size = models.PositiveBigIntegerField(default=0)
    uploaded_time= models.DateTimeField(auto_now_add=True)

    def delete(self, *args, **kwargs):
        storage = self.file.storage
        name = self.file.name
        super().delete(*args, **kwargs)
        if name and storage.exists(name):
            storage.delete(name)

    def __str__(self):
        return f"{self.original_name} ({self.owner.username})"
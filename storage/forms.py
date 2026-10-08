from datetime import timedelta

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone

from .models import Folder
from .services.uploads import UploadError, check_upload_allowed

INVALID_NAME_CHARS = set('/\\:*?"<>|')


def validate_item_name(name):
    name = name.strip()
    if name in ("", ".", ".."):
        raise forms.ValidationError("名稱不可為空白或「.」「..」")
    if INVALID_NAME_CHARS & set(name):
        raise forms.ValidationError('名稱不可包含下列字元：/ \\ : * ? " < > |')
    return name


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=False, label="Email")

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_clean(item, initial) for item in data]
        return [single_clean(data, initial)]


class FolderChoiceMixin:
    """把 folder 欄位的選項限制在目前使用者自己的資料夾。"""

    def limit_folders(self, field_name, user):
        field = self.fields[field_name]
        field.queryset = Folder.objects.active().filter(owner=user).select_related("parent")
        field.label_from_instance = lambda folder: " / ".join(
            f.name for f in folder.ancestors()
        )


class UploadForm(FolderChoiceMixin, forms.Form):
    files = MultipleFileField(label="選擇檔案（可多選）")
    folder = forms.ModelChoiceField(
        queryset=Folder.objects.none(),
        required=False,
        empty_label="根目錄",
        label="上傳到",
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.limit_folders("folder", user)

    def clean_files(self):
        files = self.cleaned_data["files"]
        try:
            check_upload_allowed(self.user, [(f.name, f.size) for f in files])
        except UploadError as error:
            raise forms.ValidationError(error.message)
        return files


class FolderForm(forms.Form):
    name = forms.CharField(max_length=255, label="資料夾名稱")

    def __init__(self, *args, user, parent=None, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.parent = parent
        self.instance = instance
        if instance is not None:
            self.fields["name"].initial = instance.name

    def clean_name(self):
        name = validate_item_name(self.cleaned_data["name"])
        siblings = Folder.objects.active().filter(owner=self.user, parent=self.parent, name=name)
        if self.instance is not None:
            siblings = siblings.exclude(pk=self.instance.pk)
        if siblings.exists():
            raise forms.ValidationError("同一個位置已經有相同名稱的資料夾")
        return name


class RenameFileForm(forms.Form):
    name = forms.CharField(max_length=255, label="新檔名")

    def clean_name(self):
        return validate_item_name(self.cleaned_data["name"])


class MoveFileForm(FolderChoiceMixin, forms.Form):
    folder = forms.ModelChoiceField(
        queryset=Folder.objects.none(),
        required=False,
        empty_label="根目錄",
        label="移動到",
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.limit_folders("folder", user)


class TwoFactorCodeForm(forms.Form):
    code = forms.CharField(
        max_length=20,
        label="驗證碼",
        help_text="驗證 App 上的 6 位數字，或一組備用碼",
        widget=forms.TextInput(attrs={"autocomplete": "one-time-code", "autofocus": True,
                                      "inputmode": "text"}),
    )


class DisableTwoFactorForm(forms.Form):
    password = forms.CharField(label="目前的密碼", widget=forms.PasswordInput)
    code = forms.CharField(max_length=20, label="驗證碼或備用碼",
                           widget=forms.TextInput(attrs={"autocomplete": "one-time-code"}))

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise forms.ValidationError("密碼不正確")
        return password


class ShareLinkForm(forms.Form):
    EXPIRY_CHOICES = [
        ("1", "1 天"),
        ("7", "7 天"),
        ("30", "30 天"),
        ("", "永不過期"),
    ]
    expires_in_days = forms.ChoiceField(
        choices=EXPIRY_CHOICES, required=False, initial="7", label="有效期限"
    )
    password = forms.CharField(
        required=False,
        max_length=128,
        label="密碼",
        help_text="留空則不需要密碼",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    max_downloads = forms.IntegerField(
        required=False, min_value=1, label="下載次數上限", help_text="留空則不限制"
    )

    def expires_time(self):
        days = self.cleaned_data.get("expires_in_days")
        if not days:
            return None
        return timezone.now() + timedelta(days=int(days))


class ChunkedUploadStartForm(forms.Form):
    name = forms.CharField(max_length=1024)
    size = forms.IntegerField(min_value=0)
    folder = forms.ModelChoiceField(queryset=Folder.objects.none(), required=False)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["folder"].queryset = Folder.objects.active().filter(owner=user)


class ChunkForm(forms.Form):
    offset = forms.IntegerField(min_value=0)
    chunk = forms.FileField(allow_empty_file=True)


class SharePasswordForm(forms.Form):
    password = forms.CharField(label="密碼", widget=forms.PasswordInput(attrs={"autofocus": True}))

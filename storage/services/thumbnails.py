"""圖片縮圖：第一次瀏覽時產生並快取在 MEDIA_ROOT/thumbs/。"""
import os
import tempfile
from pathlib import Path

from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError


def get_thumbnail_path(stored_file):
    """回傳縮圖的實體路徑；無法產生時回傳 None。"""
    if not stored_file.is_image:
        return None

    storage = stored_file.file.storage
    path = Path(storage.path(stored_file.thumbnail_name))
    if path.exists():
        return path

    size = settings.STORAGE_THUMBNAIL_SIZE
    try:
        with stored_file.file.open("rb") as fh, Image.open(fh) as image:
            # Image.open 只讀取檔頭，在真正解碼前先檢查尺寸，避免「解壓縮炸彈」
            # 用一個小檔案耗盡伺服器記憶體
            width, height = image.size
            if width * height > settings.STORAGE_THUMBNAIL_MAX_PIXELS:
                return None
            # JPEG 可以在解碼時直接縮小，大幅減少記憶體用量
            image.draft("RGB", (size * 2, size * 2))
            image = ImageOps.exif_transpose(image)
            image.thumbnail((size, size))
            if image.mode in ("RGBA", "LA", "P"):
                image = image.convert("RGBA")
                background = Image.new("RGB", image.size, "white")
                background.paste(image, mask=image.getchannel("A"))
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")

            path.parent.mkdir(parents=True, exist_ok=True)
            # 先寫入暫存檔再搬移，避免同時請求讀到寫到一半的縮圖
            fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            with os.fdopen(fd, "wb") as out:
                image.save(out, "JPEG", quality=80)
            os.replace(tmp_name, path)
    except (FileNotFoundError, UnidentifiedImageError, Image.DecompressionBombError, OSError,
            ValueError):
        return None
    return path


def delete_thumbnail(storage, file_name):
    storage.delete(f"thumbs/{file_name}.jpg")

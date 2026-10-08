"""兩步驟驗證：TOTP（RFC 6238，相容 Google Authenticator 等 App）與備用碼。"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

import qrcode
import qrcode.image.svg
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare

from ..models import RecoveryCode, UserProfile

ISSUER = "Cloud Drive"
PERIOD = 30
DIGITS = 6
# 允許前後各一個時間區段的誤差（手機時間不準時）
VALID_WINDOW = 1
RECOVERY_CODE_COUNT = 10


def generate_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode()


def current_step(now=None):
    return int((time.time() if now is None else now) // PERIOD)


def totp(secret, step):
    key = base64.b32decode(secret)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 10**DIGITS
    return f"{code:0{DIGITS}d}"


def match_step(secret, code, last_step=0, now=None):
    """驗證碼正確時回傳對應的時間區段；已經用過的區段不再接受。"""
    code = code.strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    step_now = current_step(now)
    for step in range(step_now - VALID_WINDOW, step_now + VALID_WINDOW + 1):
        if step > last_step and constant_time_compare(totp(secret, step), code):
            return step
    return None


def provisioning_uri(secret, username):
    label = quote(f"{ISSUER}:{username}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}&digits={DIGITS}&period={PERIOD}"


def qr_code_svg(data):
    image = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=8)
    return image.to_string(encoding="unicode")


def _normalize_recovery(code):
    return code.strip().replace("-", "").replace(" ", "").lower()


def _hash_recovery(code):
    return hashlib.sha256(_normalize_recovery(code).encode()).hexdigest()


@transaction.atomic
def generate_recovery_codes(user):
    """產生新的備用碼（舊的全部作廢），只會在這時候顯示一次明碼。"""
    RecoveryCode.objects.filter(user=user).delete()
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = secrets.token_hex(6)
        codes.append(f"{raw[:4]}-{raw[4:8]}-{raw[8:]}")
    RecoveryCode.objects.bulk_create(
        RecoveryCode(user=user, code_hash=_hash_recovery(code)) for code in codes
    )
    return codes


def remaining_recovery_codes(user):
    return RecoveryCode.objects.filter(user=user, used_time__isnull=True).count()


def _use_recovery_code(user, code):
    if len(_normalize_recovery(code)) != 12:
        return False
    candidate = RecoveryCode.objects.filter(
        user=user, code_hash=_hash_recovery(code), used_time__isnull=True
    ).first()
    if candidate is None:
        return False
    # 條件式更新，避免同一組備用碼被同時使用兩次
    return bool(
        RecoveryCode.objects.filter(pk=candidate.pk, used_time__isnull=True)
        .update(used_time=timezone.now())
    )


def verify(user, code):
    """驗證登入時輸入的驗證碼或備用碼。"""
    profile = UserProfile.for_user(user)
    if not profile.totp_enabled:
        return False
    step = match_step(profile.totp_secret, code, profile.totp_last_step)
    if step is not None:
        return bool(
            UserProfile.objects.filter(pk=profile.pk, totp_last_step__lt=step)
            .update(totp_last_step=step)
        )
    return _use_recovery_code(user, code)


@transaction.atomic
def enable(user, secret, step):
    profile = UserProfile.for_user(user)
    profile.totp_secret = secret
    profile.totp_enabled = True
    profile.totp_last_step = step
    profile.save(update_fields=["totp_secret", "totp_enabled", "totp_last_step"])
    return generate_recovery_codes(user)


@transaction.atomic
def disable(user):
    profile = UserProfile.for_user(user)
    profile.totp_secret = ""
    profile.totp_enabled = False
    profile.totp_last_step = 0
    profile.save(update_fields=["totp_secret", "totp_enabled", "totp_last_step"])
    RecoveryCode.objects.filter(user=user).delete()


def is_enabled(user):
    return UserProfile.for_user(user).totp_enabled

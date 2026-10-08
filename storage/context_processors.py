from django.conf import settings


def site_settings(request):
    return {"allow_registration": settings.ALLOW_REGISTRATION}

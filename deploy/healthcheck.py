"""Docker HEALTHCHECK 使用的健康檢查腳本。

在容器內以 HTTP 呼叫網站的 /<SECRET_URL_PREFIX>/healthz/，回應 200 時結束碼為 0。
不需要額外安裝 curl。
"""
import json
import os
import sys
import urllib.error
import urllib.request


def host_header():
    # Django 只接受 ALLOWED_HOSTS 裡的主機名稱，用第一個設定值
    hosts = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "localhost").split(",")]
    host = next((h for h in hosts if h and h != "*"), "localhost")
    return host.lstrip(".")


def main():
    prefix = os.environ.get("SECRET_URL_PREFIX", "x8FqP2vM4wA1").strip("/")
    port = os.environ.get("PORT", "8000")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/{prefix}/healthz/", headers={"Host": host_header()}
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            body = json.load(response)
    except urllib.error.HTTPError as error:
        print(f"健康檢查失敗：HTTP {error.code} {error.read()[:500].decode(errors='replace')}")
        return 1
    except (urllib.error.URLError, OSError, ValueError) as error:
        print(f"無法連線到網站：{error}")
        return 1
    print(json.dumps(body, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

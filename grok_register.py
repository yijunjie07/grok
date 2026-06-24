#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Grok 注册机 - TTK GUI 版本
整合 DrissionPage_example.py, openai_register.py, batch_open_nsfw.py
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import datetime
import time
import os
import sys
import queue
import subprocess
import traceback
import secrets
import struct
import random
import re
import string
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from DrissionPage import Chromium, ChromiumOptions
from DrissionPage.errors import PageDisconnectedError
from curl_cffi import requests
import atexit
import tempfile
import shutil
import stat

_all_browsers = set()
_all_browsers_lock = threading.Lock()

def register_browser(browser_obj):
    with _all_browsers_lock:
        _all_browsers.add(browser_obj)

def unregister_browser(browser_obj):
    with _all_browsers_lock:
        _all_browsers.discard(browser_obj)

def quit_all_browsers():
    with _all_browsers_lock:
        browsers = list(_all_browsers)
    for b in browsers:
        try:
            b.quit()
        except Exception:
            pass
    with _all_browsers_lock:
        _all_browsers.clear()

def clean_drissionpage_temp_dir():
    dp_temp = os.path.join(tempfile.gettempdir(), 'DrissionPage')
    if not os.path.exists(dp_temp):
        return
    def remove_readonly(func, path, excinfo):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except Exception:
            pass
    try:
        for entry in os.scandir(dp_temp):
            if entry.is_dir():
                if entry.name == 'autoPortData' or entry.name.isdigit():
                    if entry.name == 'autoPortData':
                        try:
                            for sub_entry in os.scandir(entry.path):
                                if sub_entry.is_dir():
                                    try:
                                        shutil.rmtree(sub_entry.path, onerror=remove_readonly)
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                    else:
                        try:
                            shutil.rmtree(entry.path, onerror=remove_readonly)
                        except Exception:
                            pass
    except Exception:
        pass

def async_clean_temp_dir():
    time.sleep(3)
    clean_drissionpage_temp_dir()

def start_async_clean():
    t = threading.Thread(target=async_clean_temp_dir, daemon=True)
    t.start()

def _on_system_exit():
    quit_all_browsers()
    clean_drissionpage_temp_dir()

atexit.register(_on_system_exit)


CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULT_CONFIG = {
    "duckmail_api_key": "",
    "email_provider": "duckmail",
    "yyds_api_key": "",
    "yyds_jwt": "",
    "cfmail_api_base": "",
    "cfmail_admin_auth": "",
    "cfmail_custom_auth": "",
    "cfmail_domain": "",
    "cfmail_enable_prefix": False,
    "cfmail_enable_random_subdomain": False,
    "proxy": "http://127.0.0.1:7890",
    "enable_nsfw": True,
    "register_count": 1,
    "concurrent_workers": 1,
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
}

config = DEFAULT_CONFIG.copy()


class RegistrationCancelled(Exception):
    pass


def load_config():
    global config
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            config = {**DEFAULT_CONFIG, **loaded}
        except Exception:
            config = DEFAULT_CONFIG.copy()
    return config


def save_config():
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"保存配置失败: {e}")


def ensure_stable_python_runtime():
    if sys.version_info < (3, 14) or os.environ.get("DPE_REEXEC_DONE") == "1":
        return

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    candidates = []
    for version in ("3.12", "3.13"):
        try:
            output = subprocess.check_output(
                ["py", f"-{version}", "-c", "import sys; print(sys.executable)"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).strip()
        except Exception:
            output = ""
        if output:
            candidates.append(output)

    candidates.extend(
        [
        os.path.join(local_app_data, "Programs", "Python", "Python312", "python.exe"),
        os.path.join(local_app_data, "Programs", "Python", "Python313", "python.exe"),
        ]
    )

    current_python = os.path.normcase(os.path.abspath(sys.executable))
    checked = set()
    for candidate in candidates:
        candidate = os.path.abspath(candidate)
        normalized_candidate = os.path.normcase(candidate)
        if normalized_candidate in checked:
            continue
        checked.add(normalized_candidate)
        if not os.path.isfile(candidate):
            continue
        if normalized_candidate == current_python:
            return

        print(
            f"[*] 检测到 Python {sys.version.split()[0]}，自动切换到更稳定的解释器: {candidate}",
            flush=True,
        )
        env = os.environ.copy()
        env["DPE_REEXEC_DONE"] = "1"
        os.execve(candidate, [candidate, os.path.abspath(__file__), *sys.argv[1:]], env)


def warn_runtime_compatibility():
    if sys.version_info >= (3, 14):
        print(
            "[提示] 当前 Python 为 3.14+；若出现 [Errno 22] Invalid argument，请改用 Python 3.12 或 3.13。"
        )


ensure_stable_python_runtime()
warn_runtime_compatibility()

load_config()

co = ChromiumOptions()
co.auto_port()
co.set_timeouts(base=1)

EXTENSION_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "turnstilePatch")
)
if os.path.exists(EXTENSION_PATH):
    co.add_extension(EXTENSION_PATH)


def build_chromium_options():
    options = ChromiumOptions()
    options.auto_port()
    options.set_timeouts(base=1)
    if os.path.exists(EXTENSION_PATH):
        options.add_extension(EXTENSION_PATH)
    return options


DUCKMAIL_API_BASE = "https://api.duckmail.sbs"


def get_proxies():
    proxy = config.get("proxy", "")
    if proxy:
        return {"http": proxy, "https": proxy}
    return {}


def get_duckmail_api_key():
    return config.get("duckmail_api_key", "")


def get_user_agent():
    return config.get(
        "user_agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    )


def _build_request_kwargs(**kwargs):
    request_kwargs = dict(kwargs)
    proxies = request_kwargs.pop("proxies", None)
    if proxies is None:
        proxies = get_proxies()
    if proxies:
        request_kwargs["proxies"] = proxies
    request_kwargs.setdefault("timeout", 15)
    return request_kwargs


def http_get(url, **kwargs):
    return requests.get(url, **_build_request_kwargs(**kwargs))


def http_post(url, **kwargs):
    return requests.post(url, **_build_request_kwargs(**kwargs))


def raise_if_cancelled(cancel_callback=None):
    if cancel_callback and cancel_callback():
        raise RegistrationCancelled("用户停止注册")


def sleep_with_cancel(seconds, cancel_callback=None):
    deadline = time.time() + max(seconds, 0)
    while True:
        raise_if_cancelled(cancel_callback)
        remaining = deadline - time.time()
        if remaining <= 0:
            return
        time.sleep(min(0.2, remaining))


def format_exception_for_log(exc):
    lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    tail = "".join(lines[-8:]).strip()
    return f"{type(exc).__name__}: {exc}\n{tail}"


def get_domains(api_key=None):
    headers = {}
    key = api_key or get_duckmail_api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    resp = http_get(f"{DUCKMAIL_API_BASE}/domains", headers=headers)
    resp.raise_for_status()
    return resp.json().get("hydra:member", [])


def create_account(address, password, api_key=None, expires_in=0):
    headers = {"Content-Type": "application/json"}
    key = api_key or get_duckmail_api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data = {"address": address, "password": password, "expiresIn": expires_in}
    resp = http_post(f"{DUCKMAIL_API_BASE}/accounts", json=data, headers=headers)
    resp.raise_for_status()
    return resp.json()


def get_token(address, password):
    data = {"address": address, "password": password}
    resp = http_post(f"{DUCKMAIL_API_BASE}/token", json=data)
    resp.raise_for_status()
    return resp.json().get("token")


def get_messages(token):
    headers = {"Authorization": f"Bearer {token}"}
    resp = http_get(f"{DUCKMAIL_API_BASE}/messages", headers=headers)
    resp.raise_for_status()
    return resp.json().get("hydra:member", [])


def get_message_detail(token, message_id):
    headers = {"Authorization": f"Bearer {token}"}
    resp = http_get(f"{DUCKMAIL_API_BASE}/messages/{message_id}", headers=headers)
    resp.raise_for_status()
    return resp.json()


# ===================== YYDS Mail API =====================
YYDS_API_BASE = "https://maliapi.215.im/v1"


def get_yyds_api_key():
    return config.get("yyds_api_key", "")


def get_yyds_jwt():
    return config.get("yyds_jwt", "")


def yyds_get_domains(api_key=None, jwt=None):
    key = api_key or get_yyds_api_key()
    token = jwt or get_yyds_jwt()
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif key:
        headers["X-API-Key"] = key
    resp = http_get(f"{YYDS_API_BASE}/domains", headers=headers)
    resp.raise_for_status()
    data = resp.json()
    return data.get("data", []) if data.get("success") else []


def yyds_create_account(address=None, domain=None, api_key=None, jwt=None):
    key = api_key or get_yyds_api_key()
    token = jwt or get_yyds_jwt()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif key:
        headers["X-API-Key"] = key
    payload = {}
    if address:
        payload["address"] = address
    if domain:
        payload["domain"] = domain
    elif key or token:
        payload["autoDomainStrategy"] = "prefer_owned"
    resp = http_post(f"{YYDS_API_BASE}/accounts", json=payload, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    if data.get("success"):
        return data.get("data", {})
    raise Exception(f"YYDS 创建邮箱失败: {data}")


def yyds_get_token(address, api_key=None, jwt=None):
    key = api_key or get_yyds_api_key()
    token = jwt or get_yyds_jwt()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif key:
        headers["X-API-Key"] = key
    resp = http_post(
        f"{YYDS_API_BASE}/token", json={"address": address}, headers=headers
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("success"):
        return data.get("data", {}).get("token")
    raise Exception(f"YYDS 获取token失败: {data}")


def yyds_get_messages(address, token=None, api_key=None, jwt=None):
    key = api_key or get_yyds_api_key()
    temp_token = token or jwt or get_yyds_jwt()
    headers = {}
    if temp_token:
        headers["Authorization"] = f"Bearer {temp_token}"
    elif key:
        headers["X-API-Key"] = key
    resp = http_get(
        f"{YYDS_API_BASE}/messages",
        params={"address": address},
        headers=headers,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("success"):
        return data.get("data", {}).get("messages", [])
    return []


def yyds_get_message_detail(message_id, token=None, api_key=None, jwt=None):
    key = api_key or get_yyds_api_key()
    temp_token = token or jwt or get_yyds_jwt()
    headers = {}
    if temp_token:
        headers["Authorization"] = f"Bearer {temp_token}"
    elif key:
        headers["X-API-Key"] = key
    resp = http_get(f"{YYDS_API_BASE}/messages/{message_id}", headers=headers)
    resp.raise_for_status()
    data = resp.json()
    if data.get("success"):
        return data.get("data", {})
    raise Exception(f"YYDS 获取邮件详情失败: {data}")


def yyds_generate_username(length=10):
    chars = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def yyds_pick_domain(api_key=None, jwt=None):
    domains = yyds_get_domains(api_key=api_key, jwt=jwt)
    if not domains:
        raise Exception("YYDS 没有返回任何可用域名")
    private = [d for d in domains if d.get("isVerified") and not d.get("isPublic")]
    if private:
        return private[0]["domain"]
    public = [d for d in domains if d.get("isVerified") and d.get("isPublic")]
    if public:
        return public[0]["domain"]
    verified = [d for d in domains if d.get("isVerified")]
    if verified:
        return verified[0]["domain"]
    raise Exception("YYDS 无已验证域名可用")


def yyds_get_email_and_token(api_key=None, jwt=None):
    key = api_key or get_yyds_api_key()
    token = jwt or get_yyds_jwt()
    if not token and not key:
        raise Exception("YYDS API Key 或 JWT 未配置")
    domain = yyds_pick_domain(api_key=key, jwt=token)
    username = yyds_generate_username(10)
    result = yyds_create_account(
        address=username, domain=domain, api_key=key, jwt=token
    )
    address = result.get("address") or f"{username}@{domain}"
    temp_token = result.get("token")
    if not temp_token:
        temp_token = yyds_get_token(address, api_key=key, jwt=token)
    if not temp_token:
        raise Exception("获取 YYDS token 失败")
    print(f"[*] 已创建 YYDS 邮箱: {address}")
    return address, temp_token


def yyds_get_oai_code(
    token,
    address,
    timeout=180,
    poll_interval=3,
    log_callback=None,
    jwt=None,
    cancel_callback=None,
):
    deadline = time.time() + timeout
    seen_ids = set()
    while time.time() < deadline:
        raise_if_cancelled(cancel_callback)
        try:
            messages = yyds_get_messages(address, token=token, jwt=jwt)
        except Exception as exc:
            if log_callback:
                log_callback(f"[Debug] YYDS 拉取邮件列表失败: {exc}")
            sleep_with_cancel(poll_interval, cancel_callback)
            continue
        for msg in messages:
            msg_id = msg.get("id")
            if not msg_id or msg_id in seen_ids:
                continue
            seen_ids.add(msg_id)
            to_addrs = [t.get("address", "").lower() for t in (msg.get("to") or [])]
            if address.lower() not in to_addrs:
                continue
            try:
                detail = yyds_get_message_detail(msg_id, token=token, jwt=jwt)
            except Exception as exc:
                if log_callback:
                    log_callback(f"[Debug] YYDS 获取邮件详情失败: {exc}")
                continue
            parts = []
            text_body = detail.get("text") or ""
            if text_body:
                parts.append(text_body)
            html_list = detail.get("html") or []
            for h in html_list:
                parts.append(re.sub(r"<[^>]+>", " ", h))
            combined = "\n".join(parts)
            subject = detail.get("subject", "")
            if log_callback:
                log_callback(f"[Debug] YYDS 收到邮件: {subject}")
            code = extract_verification_code(combined, subject)
            if code:
                if log_callback:
                    log_callback(f"[*] YYDS 从邮件中提取到验证码: {code}")
                return code
        sleep_with_cancel(poll_interval, cancel_callback)
    raise Exception(f"YYDS 在 {timeout}s 内未收到验证码邮件")


# ===================== Cloudflare Temp Email API =====================
def get_cfmail_api_base():
    return config.get("cfmail_api_base", "").strip().rstrip("/")


def get_cfmail_admin_auth():
    return config.get("cfmail_admin_auth", "").strip()


def get_cfmail_custom_auth():
    return config.get("cfmail_custom_auth", "").strip()


def get_cfmail_domain():
    return config.get("cfmail_domain", "").strip()


def cfmail_admin_headers():
    headers = {"Content-Type": "application/json"}
    admin_auth = get_cfmail_admin_auth()
    custom_auth = get_cfmail_custom_auth()
    if admin_auth:
        headers["x-admin-auth"] = admin_auth
    if custom_auth:
        headers["x-custom-auth"] = custom_auth
    return headers


def cfmail_address_headers(address_jwt):
    headers = {"Authorization": f"Bearer {address_jwt}"}
    custom_auth = get_cfmail_custom_auth()
    if custom_auth:
        headers["x-custom-auth"] = custom_auth
    return headers


def cfmail_generate_username(length=12):
    chars = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def cfmail_create_address(name=None):
    base = get_cfmail_api_base()
    if not base:
        raise Exception("Cloudflare Mail API 地址未配置")
    if not get_cfmail_admin_auth():
        raise Exception("Cloudflare Mail Admin 密码未配置")

    payload = {
        "name": name or cfmail_generate_username(),
        "enablePrefix": bool(config.get("cfmail_enable_prefix", False)),
    }
    domain = get_cfmail_domain()
    if domain:
        payload["domain"] = domain
    if config.get("cfmail_enable_random_subdomain", False):
        payload["enableRandomSubdomain"] = True

    resp = http_post(
        f"{base}/admin/new_address",
        json=payload,
        headers=cfmail_admin_headers(),
        proxies={},
    )
    if resp.status_code >= 400:
        raise Exception(f"Cloudflare Mail 创建邮箱失败: {resp.status_code} {resp.text[:300]}")
    return resp.json()


def cfmail_get_email_and_token():
    last_error = None
    for _ in range(5):
        try:
            result = cfmail_create_address(cfmail_generate_username())
            address = result.get("address")
            token = result.get("jwt")
            if address and token:
                print(f"[*] 已创建 Cloudflare Mail 邮箱: {address}")
                return address, token
            last_error = Exception(f"Cloudflare Mail 返回缺少 address/jwt: {result}")
        except Exception as exc:
            last_error = exc
            error_text = str(exc).lower()
            if "already exists" not in error_text and "已存在" not in error_text:
                break
    raise last_error or Exception("Cloudflare Mail 创建邮箱失败")


def cfmail_get_parsed_mails(address_jwt, limit=20):
    base = get_cfmail_api_base()
    resp = http_get(
        f"{base}/api/parsed_mails",
        params={"limit": limit, "offset": 0},
        headers=cfmail_address_headers(address_jwt),
        proxies={},
    )
    if resp.status_code >= 400:
        raise Exception(f"Cloudflare Mail 拉取邮件失败: {resp.status_code} {resp.text[:300]}")
    data = resp.json()
    return data.get("results", []) if isinstance(data, dict) else []


def cfmail_list_addresses(query=None, limit=20):
    base = get_cfmail_api_base()
    params = {"limit": limit, "offset": 0}
    if query:
        params["query"] = query
    resp = http_get(
        f"{base}/admin/address",
        params=params,
        headers=cfmail_admin_headers(),
        proxies={},
    )
    if resp.status_code >= 400:
        raise Exception(f"Cloudflare Mail 查询邮箱失败: {resp.status_code} {resp.text[:300]}")
    return resp.json()


def cfmail_delete_address(address_id):
    base = get_cfmail_api_base()
    resp = requests.delete(
        f"{base}/admin/delete_address/{address_id}",
        **_build_request_kwargs(headers=cfmail_admin_headers(), proxies={}),
    )
    if resp.status_code >= 400:
        raise Exception(f"Cloudflare Mail 删除邮箱失败: {resp.status_code} {resp.text[:300]}")
    return resp.json()


def cfmail_message_text(message):
    parts = [
        message.get("subject") or "",
        message.get("text") or "",
    ]
    html = message.get("html") or ""
    if isinstance(html, list):
        html = "\n".join(str(item) for item in html)
    if html:
        parts.append(re.sub(r"<[^>]+>", " ", str(html)))
    return "\n".join(parts)


def cfmail_get_oai_code(
    address_jwt,
    email,
    timeout=180,
    poll_interval=3,
    log_callback=None,
    cancel_callback=None,
):
    deadline = time.time() + timeout
    seen_ids = set()
    while time.time() < deadline:
        raise_if_cancelled(cancel_callback)
        try:
            messages = cfmail_get_parsed_mails(address_jwt)
        except Exception as exc:
            if log_callback:
                log_callback(f"[Debug] Cloudflare Mail 拉取邮件列表失败: {exc}")
            sleep_with_cancel(poll_interval, cancel_callback)
            continue

        for msg in messages:
            msg_id = msg.get("id") or msg.get("message_id")
            if msg_id and msg_id in seen_ids:
                continue
            if msg_id:
                seen_ids.add(msg_id)

            recipient = str(msg.get("to") or "").lower()
            if recipient and email.lower() not in recipient:
                continue

            subject = msg.get("subject", "")
            if log_callback:
                log_callback(f"[Debug] Cloudflare Mail 收到邮件: {subject}")
            code = extract_verification_code(cfmail_message_text(msg), subject)
            if code:
                if log_callback:
                    log_callback(f"[*] Cloudflare Mail 从邮件中提取到验证码: {code}")
                return code

        sleep_with_cancel(poll_interval, cancel_callback)
    raise Exception(f"Cloudflare Mail 在 {timeout}s 内未收到验证码邮件")


def generate_username(length=10):
    import string

    chars = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def pick_domain(api_key=None):
    domains = get_domains(api_key=api_key)
    if not domains:
        raise Exception("DuckMail 没有返回任何可用域名")
    private = [d for d in domains if d.get("ownerId")]
    verified_private = [d for d in private if d.get("isVerified")]
    if verified_private:
        return verified_private[0]["domain"]
    public = [d for d in domains if d.get("isVerified")]
    if public:
        return public[0]["domain"]
    raise Exception("DuckMail 无已验证域名可用")


def get_email_provider():
    return config.get("email_provider", "duckmail")


def get_email_and_token(api_key=None):
    provider = get_email_provider()
    if provider == "yyds":
        return yyds_get_email_and_token(api_key=api_key, jwt=get_yyds_jwt())
    if provider == "cloudflare":
        return cfmail_get_email_and_token()
    key = api_key or get_duckmail_api_key()
    domain = pick_domain(api_key=key)
    username = generate_username(10)
    address = f"{username}@{domain}"
    password = secrets.token_urlsafe(12)
    create_account(address, password, api_key=key, expires_in=0)
    token = get_token(address, password)
    if not token:
        raise Exception("获取 DuckMail token 失败")
    return address, token


def get_oai_code(
    dev_token,
    email,
    timeout=180,
    poll_interval=3,
    log_callback=None,
    cancel_callback=None,
):
    provider = get_email_provider()
    if provider == "yyds":
        return yyds_get_oai_code(
            dev_token,
            email,
            timeout=timeout,
            poll_interval=poll_interval,
            log_callback=log_callback,
            jwt=get_yyds_jwt(),
            cancel_callback=cancel_callback,
        )
    if provider == "cloudflare":
        return cfmail_get_oai_code(
            dev_token,
            email,
            timeout=timeout,
            poll_interval=poll_interval,
            log_callback=log_callback,
            cancel_callback=cancel_callback,
        )
    return duckmail_get_oai_code(
        dev_token,
        email,
        timeout=timeout,
        poll_interval=poll_interval,
        log_callback=log_callback,
        cancel_callback=cancel_callback,
    )


def extract_verification_code(text, subject=""):
    if subject:
        match = re.search(r"^([A-Z0-9]{3}-[A-Z0-9]{3})\s+xAI", subject, re.IGNORECASE)
        if match:
            return match.group(1)
    match = re.search(r"\b([A-Z0-9]{3}-[A-Z0-9]{3})\b", text, re.IGNORECASE)
    if match:
        return match.group(1)
    patterns = [
        r"verification\s+code[:\s]+(\d{4,8})",
        r"your\s+code[:\s]+(\d{4,8})",
        r"confirm(?:ation)?\s+code[:\s]+(\d{4,8})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def duckmail_get_oai_code(
    dev_token,
    email,
    timeout=180,
    poll_interval=3,
    log_callback=None,
    cancel_callback=None,
):
    deadline = time.time() + timeout
    seen_ids = set()
    while time.time() < deadline:
        raise_if_cancelled(cancel_callback)
        try:
            messages = get_messages(dev_token)
        except Exception as exc:
            if log_callback:
                log_callback(f"[Debug] 拉取邮件列表失败: {exc}")
            sleep_with_cancel(poll_interval, cancel_callback)
            continue
        for msg in messages:
            msg_id = msg.get("id") or msg.get("msgid")
            if not msg_id or msg_id in seen_ids:
                continue
            seen_ids.add(msg_id)
            recipients = [t.get("address", "").lower() for t in (msg.get("to") or [])]
            if email.lower() not in recipients:
                continue
            try:
                detail = get_message_detail(dev_token, msg_id)
            except Exception as exc:
                if log_callback:
                    log_callback(f"[Debug] 获取邮件详情失败: {exc}")
                continue
            parts = []
            text_body = detail.get("text") or ""
            if text_body:
                parts.append(text_body)
            html_list = detail.get("html") or []
            for h in html_list:
                parts.append(re.sub(r"<[^>]+>", " ", h))
            combined = "\n".join(parts)
            subject = detail.get("subject", "")
            if log_callback:
                log_callback(f"[Debug] 收到邮件: {subject}")
            code = extract_verification_code(combined, subject)
            if code:
                if log_callback:
                    log_callback(f"[*] 从邮件中提取到验证码: {code}")
                return code
        sleep_with_cancel(poll_interval, cancel_callback)
    raise Exception(f"在 {timeout}s 内未收到验证码邮件")


# ===================== NSFW 设置 (来自 batch_open_nsfw.py) =====================
def generate_random_birthdate():
    import datetime as dt

    today = dt.date.today()
    age = random.randint(20, 40)
    birth_year = today.year - age
    birth_month = random.randint(1, 12)
    birth_day = random.randint(1, 28)
    return f"{birth_year}-{birth_month:02d}-{birth_day:02d}T16:00:00.000Z"


def set_birth_date(session, log_callback=None):
    url = "https://grok.com/rest/auth/set-birth-date"
    new_headers = {
        "content-type": "application/json",
        "origin": "https://grok.com",
        "referer": "https://grok.com/",
    }
    payload = {"birthDate": generate_random_birthdate()}
    try:
        res = session.post(url, json=payload, headers=new_headers, timeout=15)
        if log_callback:
            log_callback(
                f"[Debug] set_birth_date status: {res.status_code}, body: {res.text[:200]}"
            )
        return res.status_code == 200
    except Exception as e:
        if log_callback:
            log_callback(f"[set_birth_date] 异常: {e}")
        return False


def set_tos_accepted(session, log_callback=None):
    url = "https://accounts.x.ai/auth_mgmt.AuthManagement/SetTosAcceptedVersion"
    payload = struct.pack("B", (2 << 3) | 0) + struct.pack("B", 1)
    data = b"\x00" + struct.pack(">I", len(payload)) + payload
    new_headers = {
        "content-type": "application/grpc-web+proto",
        "x-grpc-web": "1",
        "x-user-agent": "connect-es/2.1.1",
        "origin": "https://accounts.x.ai",
        "referer": "https://accounts.x.ai/accept-tos",
    }
    try:
        res = session.post(url, data=data, headers=new_headers, timeout=15)
        if log_callback:
            log_callback(f"[Debug] set_tos_accepted status: {res.status_code}")
        return res.status_code == 200
    except Exception as e:
        if log_callback:
            log_callback(f"[set_tos_accepted] 异常: {e}")
        return False


def encode_grpc_nsfw_settings():
    field1_content = bytes([0x10, 0x01])
    field1 = bytes([0x0A, len(field1_content)]) + field1_content
    nsfw_string = b"always_show_nsfw_content"
    field2_inner = bytes([0x0A, len(nsfw_string)]) + nsfw_string
    field2 = bytes([0x12, len(field2_inner)]) + field2_inner
    payload = field1 + field2
    return b"\x00" + struct.pack(">I", len(payload)) + payload


def update_nsfw_settings(session, log_callback=None):
    url = "https://grok.com/auth_mgmt.AuthManagement/UpdateUserFeatureControls"
    data = encode_grpc_nsfw_settings()
    new_headers = {
        "content-type": "application/grpc-web+proto",
        "x-grpc-web": "1",
        "origin": "https://grok.com",
        "referer": "https://grok.com/",
    }
    try:
        res = session.post(url, data=data, headers=new_headers, timeout=15)
        if log_callback:
            log_callback(f"[Debug] update_nsfw status: {res.status_code}")
        return res.status_code == 200
    except Exception as e:
        if log_callback:
            log_callback(f"[update_nsfw] 异常: {e}")
        return False


def enable_nsfw_for_token(token, cf_clearance="", log_callback=None):
    proxies = get_proxies()
    user_agent = get_user_agent()
    try:
        with requests.Session(impersonate="chrome120", proxies=proxies) as session:
            session.headers.update(
                {
                    "user-agent": user_agent,
                    "cookie": f"sso={token}; sso-rw={token}; cf_clearance={cf_clearance}",
                }
            )
            if not set_tos_accepted(session, log_callback):
                return False, "set_tos_accepted 失败!"
            if not set_birth_date(session, log_callback):
                return False, "set_birth_date 失败!"
            if not update_nsfw_settings(session, log_callback):
                return False, "update_nsfw_settings 失败!"
            return True, "成功开启NSFW"
    except Exception as e:
        return False, f"异常: {str(e)}"


# ===================== 浏览器自动化 (来自 DrissionPage_example.py) =====================
SIGNUP_URL = "https://accounts.x.ai/sign-up?redirect=grok-com"

_browser_context = threading.local()


class ThreadLocalBrowserRef:
    def __init__(self, attr_name):
        self.attr_name = attr_name

    def _target(self):
        target = getattr(_browser_context, self.attr_name, None)
        if target is None:
            raise RuntimeError(f"{self.attr_name} is not initialized in this thread")
        return target

    def __getattr__(self, name):
        return getattr(self._target(), name)

    def __bool__(self):
        return getattr(_browser_context, self.attr_name, None) is not None


browser = ThreadLocalBrowserRef("browser")
page = ThreadLocalBrowserRef("page")


def get_thread_browser():
    return getattr(_browser_context, "browser", None)


def get_thread_page():
    return getattr(_browser_context, "page", None)


def set_thread_browser(browser_obj=None, page_obj=None):
    _browser_context.browser = browser_obj
    _browser_context.page = page_obj


def start_browser():
    browser_obj = Chromium(build_chromium_options())
    register_browser(browser_obj)
    tabs = browser_obj.get_tabs()
    page_obj = tabs[-1] if tabs else browser_obj.new_tab()
    set_thread_browser(browser_obj, page_obj)
    return browser_obj, page_obj


def stop_browser():
    browser_obj = get_thread_browser()
    if browser_obj is not None:
        try:
            browser_obj.quit()
        except Exception:
            pass
        finally:
            unregister_browser(browser_obj)
    set_thread_browser(None, None)


def restart_browser():
    browser_obj = get_thread_browser()
    if browser_obj is not None:
        try:
            browser_obj.quit()
        except Exception:
            pass
        finally:
            unregister_browser(browser_obj)
    browser_obj = Chromium(build_chromium_options())
    register_browser(browser_obj)
    tabs = browser_obj.get_tabs()
    page_obj = tabs[-1] if tabs else browser_obj.new_tab()
    set_thread_browser(browser_obj, page_obj)
    return browser_obj, page_obj


def clear_login_state(log_callback=None):
    browser_obj = get_thread_browser()
    page_obj = get_thread_page()
    try:
        if browser_obj is not None:
            browser_obj.clear_cache(cache=False, cookies=True)
        if page_obj is not None:
            page_obj.run_js(
                """
try { localStorage.clear(); } catch (e) {}
try { sessionStorage.clear(); } catch (e) {}
                """
            )
        if log_callback:
            log_callback("[*] 已清空浏览器登录态")
    except Exception as exc:
        if log_callback:
            log_callback(f"[Debug] 清空登录态失败: {exc}")


def refresh_active_page():
    browser_obj = get_thread_browser()
    if browser_obj is None:
        restart_browser()
        browser_obj = get_thread_browser()
    try:
        tabs = browser_obj.get_tabs()
        if tabs:
            page_obj = tabs[-1]
        else:
            page_obj = browser_obj.new_tab()
        set_thread_browser(browser_obj, page_obj)
    except Exception:
        restart_browser()
        page_obj = get_thread_page()
    return page_obj


def click_email_signup_button(timeout=10, log_callback=None, cancel_callback=None):
    deadline = time.time() + timeout
    while time.time() < deadline:
        raise_if_cancelled(cancel_callback)
        if log_callback:
            log_callback("[Debug] 尝试查找「使用邮箱注册」按钮...")

        clicked = page.run_js(r"""
const candidates = Array.from(document.querySelectorAll('button, a, [role="button"]'));
const target = candidates.find((node) => {
    const text = (node.innerText || node.textContent || '').replace(/\s+/g, '');
    return text.includes('使用邮箱注册');
});

if (!target) {
    return false;
}

target.click();
return true;
        """)

        if clicked:
            if log_callback:
                log_callback("[*] 已点击「使用邮箱注册」按钮")
            sleep_with_cancel(2, cancel_callback)
            return True

        if log_callback:
            current_url = page.url if page else "none"
            log_callback(f"[Debug] 当前URL: {current_url}")

        sleep_with_cancel(1, cancel_callback)

    if log_callback:
        page_html = page.html[:500] if page else "no page"
        log_callback(f"[Debug] 页面内容: {page_html}")

    raise Exception("未找到「使用邮箱注册」按钮")


def open_signup_page(log_callback=None, cancel_callback=None):
    raise_if_cancelled(cancel_callback)

    browser_obj = get_thread_browser()
    if browser_obj is None:
        start_browser()
        browser_obj = get_thread_browser()
        if log_callback:
            log_callback("[*] 浏览器已启动")

    clear_login_state(log_callback=log_callback)

    try:
        page = browser.get_tab(0)
        page.get(SIGNUP_URL)
    except Exception as e:
        if log_callback:
            log_callback(f"[Debug] 打开URL异常: {e}")
        try:
            page = browser.new_tab(SIGNUP_URL)
        except Exception as e2:
            if log_callback:
                log_callback(f"[Debug] 创建新标签页异常: {e2}")
            restart_browser()
            page = browser.new_tab(SIGNUP_URL)

    set_thread_browser(get_thread_browser(), page)
    page.wait.doc_loaded()
    sleep_with_cancel(2, cancel_callback)

    if log_callback:
        log_callback(f"[*] 当前URL: {page.url}")

    click_email_signup_button(
        log_callback=log_callback, cancel_callback=cancel_callback
    )


def has_profile_form(log_callback=None):
    refresh_active_page()
    try:
        return bool(
            page.run_js(
                """
const givenInput = document.querySelector('input[data-testid="givenName"], input[name="givenName"], input[autocomplete="given-name"]');
const familyInput = document.querySelector('input[data-testid="familyName"], input[name="familyName"], input[autocomplete="family-name"]');
const passwordInput = document.querySelector('input[data-testid="password"], input[name="password"], input[type="password"]');
return !!(givenInput && familyInput && passwordInput);
            """
            )
        )
    except Exception:
        return False


def fill_email_and_submit(timeout=15, log_callback=None, cancel_callback=None):
    raise_if_cancelled(cancel_callback)
    email, dev_token = get_email_and_token()
    if not email or not dev_token:
        raise Exception("获取邮箱失败")
    if log_callback:
        log_callback(f"[*] 已创建邮箱: {email}")

    deadline = time.time() + timeout
    while time.time() < deadline:
        raise_if_cancelled(cancel_callback)
        filled = page.run_js(
            """
const email = arguments[0];

function isVisible(node) {
    if (!node) {
        return false;
    }
    const style = window.getComputedStyle(node);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
        return false;
    }
    const rect = node.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
}

const input = Array.from(document.querySelectorAll('input[data-testid="email"], input[name="email"], input[type="email"], input[autocomplete="email"]')).find((node) => {
    return isVisible(node) && !node.disabled && !node.readOnly;
}) || null;

if (!input) {
    return 'not-ready';
}

input.focus();
input.click();

const valueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
const tracker = input._valueTracker;
if (tracker) {
    tracker.setValue('');
}
if (valueSetter) {
    valueSetter.call(input, email);
} else {
    input.value = email;
}

input.dispatchEvent(new InputEvent('beforeinput', {
    bubbles: true,
    data: email,
    inputType: 'insertText',
}));
input.dispatchEvent(new InputEvent('input', {
    bubbles: true,
    data: email,
    inputType: 'insertText',
}));
input.dispatchEvent(new Event('change', { bubbles: true }));

if ((input.value || '').trim() !== email || !input.checkValidity()) {
    return false;
}

input.blur();
return 'filled';
            """,
            email,
        )

        if filled == "not-ready":
            sleep_with_cancel(0.5, cancel_callback)
            continue

        if filled != "filled":
            if log_callback:
                log_callback(f"[Debug] 邮箱输入框已出现，但写入失败: {filled}")
            sleep_with_cancel(0.5, cancel_callback)
            continue

        if filled == "filled":
            sleep_with_cancel(0.8, cancel_callback)
            clicked = page.run_js(
                r"""
function isVisible(node) {
    if (!node) {
        return false;
    }
    const style = window.getComputedStyle(node);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
        return false;
    }
    const rect = node.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
}

const input = Array.from(document.querySelectorAll('input[data-testid="email"], input[name="email"], input[type="email"], input[autocomplete="email"]')).find((node) => {
    return isVisible(node) && !node.disabled && !node.readOnly;
}) || null;

if (!input || !input.checkValidity() || !(input.value || '').trim()) {
    return false;
}

const buttons = Array.from(document.querySelectorAll('button[type="submit"], button')).filter((node) => {
    return isVisible(node) && !node.disabled && node.getAttribute('aria-disabled') !== 'true';
});
const submitButton = buttons.find((node) => {
    const text = (node.innerText || node.textContent || '').replace(/\s+/g, '');
    return text === '注册' || text.includes('注册');
});

if (!submitButton || submitButton.disabled) {
    return false;
}

submitButton.click();
return true;
                """
            )

            if clicked:
                if log_callback:
                    log_callback(f"[*] 已填写邮箱并点击注册: {email}")
                return email, dev_token

        sleep_with_cancel(0.5, cancel_callback)

    raise Exception("未找到邮箱输入框或注册按钮")


def fill_code_and_submit(
    email, dev_token, timeout=180, log_callback=None, cancel_callback=None
):
    code = get_oai_code(
        dev_token,
        email,
        log_callback=log_callback,
        cancel_callback=cancel_callback,
    )
    if not code:
        raise Exception("获取验证码失败")

    deadline = time.time() + timeout
    while time.time() < deadline:
        raise_if_cancelled(cancel_callback)
        try:
            filled = page.run_js(
                """
const code = String(arguments[0] || '').trim();
const cleanCode = code.replace(/-/g, '');

function isVisible(node) {
    if (!node) {
        return false;
    }
    const style = window.getComputedStyle(node);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
        return false;
    }
    const rect = node.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
}

function setNativeValue(input, value) {
    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
    const tracker = input._valueTracker;
    if (tracker) {
        tracker.setValue('');
    }
    if (nativeInputValueSetter) {
        nativeInputValueSetter.call(input, '');
        nativeInputValueSetter.call(input, value);
    } else {
        input.value = '';
        input.value = value;
    }
}

function dispatchInputEvents(input, value) {
    input.dispatchEvent(new InputEvent('beforeinput', {
        bubbles: true,
        cancelable: true,
        data: value,
        inputType: 'insertText',
    }));
    input.dispatchEvent(new InputEvent('input', {
        bubbles: true,
        cancelable: true,
        data: value,
        inputType: 'insertText',
    }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
}

const input = Array.from(document.querySelectorAll('input[data-input-otp="true"], input[name="code"], input[autocomplete="one-time-code"], input[inputmode="numeric"], input[inputmode="text"]')).find((node) => {
    return isVisible(node) && !node.disabled && !node.readOnly && Number(node.maxLength || cleanCode.length || 6) > 1;
}) || null;

const otpBoxes = Array.from(document.querySelectorAll('input')).filter((node) => {
    if (!isVisible(node) || node.disabled || node.readOnly) {
        return false;
    }
    const maxLength = Number(node.maxLength || 0);
    const autocomplete = String(node.autocomplete || '').toLowerCase();
    return maxLength === 1 || autocomplete === 'one-time-code';
});

if (!input && otpBoxes.length < cleanCode.length) {
    return 'not-ready';
}

if (input) {
    input.focus();
    input.click();
    
    const originalMaxLength = input.maxLength;
    if (originalMaxLength > 0 && originalMaxLength < cleanCode.length) {
        input.removeAttribute('maxLength');
    }
    
    const originalType = input.type;
    if (originalType === 'number' || originalType === 'tel') {
        input.type = 'text';
    }
    
    setNativeValue(input, cleanCode);
    dispatchInputEvents(input, cleanCode);

    const normalizedValue = String(input.value || '').trim();
    const slots = Array.from(document.querySelectorAll('[data-input-otp-slot="true"]'));
    const filledSlots = slots.filter((slot) => (slot.textContent || '').trim()).length;

    if (normalizedValue === cleanCode) {
        input.blur();
        return 'filled';
    }
    
    if (normalizedValue.length === cleanCode.length && normalizedValue.toUpperCase() === cleanCode.toUpperCase()) {
        input.blur();
        return 'filled';
    }
    
    if (cleanCode.startsWith(normalizedValue) || normalizedValue.startsWith(cleanCode.substring(0, normalizedValue.length))) {
        input.blur();
        return 'filled';
    }

    return 'aggregate-mismatch: got=' + normalizedValue + ' expected=' + cleanCode;
}

const orderedBoxes = otpBoxes.slice(0, cleanCode.length);
for (let i = 0; i < orderedBoxes.length; i += 1) {
    const box = orderedBoxes[i];
    const char = cleanCode[i] || '';
    box.focus();
    box.click();
    setNativeValue(box, char);
    dispatchInputEvents(box, char);
    box.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: char }));
    box.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: char }));
    box.blur();
}

const merged = orderedBoxes.map((node) => String(node.value || '').trim()).join('');
return merged.toUpperCase() === cleanCode.toUpperCase() ? 'filled' : 'box-mismatch: got=' + merged + ' expected=' + cleanCode;
                """,
                code,
            )
        except PageDisconnectedError:
            refresh_active_page()
            if has_profile_form(log_callback):
                if log_callback:
                    log_callback("[*] 验证码提交后已跳转到最终注册页。")
                return code
            sleep_with_cancel(1, cancel_callback)
            continue

        if filled == "not-ready":
            if has_profile_form(log_callback):
                if log_callback:
                    log_callback("[*] 已直接进入最终注册页，跳过验证码按钮确认。")
                return code
            sleep_with_cancel(0.5, cancel_callback)
            continue

        if filled != "filled" and not filled.startswith("filled"):
            if log_callback:
                log_callback(f"[Debug] 验证码输入框已出现，但写入失败: {filled}")
            sleep_with_cancel(0.5, cancel_callback)
            continue

        if filled == "filled":
            sleep_with_cancel(1.2, cancel_callback)
            try:
                clicked = page.run_js(
                    r"""
function isVisible(node) {
    if (!node) {
        return false;
    }
    const style = window.getComputedStyle(node);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
        return false;
    }
    const rect = node.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
}

const aggregateInput = Array.from(document.querySelectorAll('input[data-input-otp="true"], input[name="code"], input[autocomplete="one-time-code"], input[inputmode="numeric"], input[inputmode="text"]')).find((node) => {
    return isVisible(node) && !node.disabled && !node.readOnly && Number(node.maxLength || 0) > 1;
}) || null;

let value = '';
if (aggregateInput) {
    value = String(aggregateInput.value || '').trim();
    if (!value) {
        return false;
    }
    if (value.length < 5) {
        return false;
    }

    const slots = Array.from(document.querySelectorAll('[data-input-otp-slot="true"]'));
    if (slots.length) {
        const filledSlots = slots.filter((slot) => (slot.textContent || '').trim()).length;
        if (filledSlots && filledSlots !== value.length) {
            return false;
        }
    }
} else {
    const otpBoxes = Array.from(document.querySelectorAll('input')).filter((node) => {
        if (!isVisible(node) || node.disabled || node.readOnly) {
            return false;
        }
        const maxLength = Number(node.maxLength || 0);
        const autocomplete = String(node.autocomplete || '').toLowerCase();
        return maxLength === 1 || autocomplete === 'one-time-code';
    });
    value = otpBoxes.map((node) => String(node.value || '').trim()).join('');
    if (!value || value.length < 5) {
        return false;
    }
}

const buttons = Array.from(document.querySelectorAll('button[type="submit"], button')).filter((node) => {
    return isVisible(node) && !node.disabled && node.getAttribute('aria-disabled') !== 'true';
});
const confirmButton = buttons.find((node) => {
    const text = (node.innerText || node.textContent || '').replace(/\s+/g, '');
    return text === '确认邮箱' || text.includes('确认邮箱') || text === '继续' || text.includes('继续') || text === '下一步' || text.includes('下一步');
});

if (!confirmButton) {
    return 'no-button';
}

confirmButton.focus();
confirmButton.click();
return 'clicked';
                    """
                )
            except PageDisconnectedError:
                refresh_active_page()
                if has_profile_form(log_callback):
                    if log_callback:
                        log_callback("[*] 确认邮箱后页面跳转成功，已进入最终注册页。")
                    return code
                clicked = "disconnected"

            if clicked == "clicked":
                if log_callback:
                    log_callback(f"[*] 已填写验证码并点击确认邮箱: {code}")
                sleep_with_cancel(2, cancel_callback)
                refresh_active_page()
                if has_profile_form(log_callback):
                    if log_callback:
                        log_callback("[*] 验证码确认完成，最终注册页已就绪。")
                return code

            if clicked == "no-button":
                current_url = page.url
                if "sign-up" in current_url or "signup" in current_url:
                    if log_callback:
                        log_callback(
                            f"[*] 已填写验证码，页面已自动跳转到下一步: {current_url}"
                        )
                    return code

            if clicked == "disconnected":
                sleep_with_cancel(1, cancel_callback)
                continue

        sleep_with_cancel(0.5, cancel_callback)

    raise Exception("未找到验证码输入框或确认邮箱按钮")


def getTurnstileToken(log_callback=None, cancel_callback=None):
    page.run_js("try { turnstile.reset() } catch(e) { }")

    turnstileResponse = None

    for i in range(0, 15):
        raise_if_cancelled(cancel_callback)
        try:
            turnstileResponse = page.run_js(
                "try { return turnstile.getResponse() } catch(e) { return null }"
            )
            if turnstileResponse:
                return turnstileResponse

            challengeSolution = page.ele("@name=cf-turnstile-response")
            challengeWrapper = challengeSolution.parent()
            challengeIframe = challengeWrapper.shadow_root.ele("tag:iframe")

            challengeIframe.run_js("""
window.dtp = 1
function getRandomInt(min, max) {
    return Math.floor(Math.random() * (max - min + 1)) + min;
}

let screenX = getRandomInt(800, 1200);
let screenY = getRandomInt(400, 600);

Object.defineProperty(MouseEvent.prototype, 'screenX', { value: screenX });
Object.defineProperty(MouseEvent.prototype, 'screenY', { value: screenY });
                        """)

            challengeIframeBody = challengeIframe.ele("tag:body").shadow_root
            challengeButton = challengeIframeBody.ele("tag:input")
            challengeButton.click()
        except:
            pass
        sleep_with_cancel(1, cancel_callback)
    raise Exception("failed to solve turnstile")


def build_profile():
    given_name = "Neo"
    family_name = "Lin"
    password = "N" + secrets.token_hex(4) + "!a7#" + secrets.token_urlsafe(6)
    return given_name, family_name, password


def fill_profile_and_submit(timeout=120, log_callback=None, cancel_callback=None):
    given_name, family_name, password = build_profile()
    deadline = time.time() + timeout
    turnstile_token = ""

    while time.time() < deadline:
        raise_if_cancelled(cancel_callback)
        filled = page.run_js(
            """
const givenName = arguments[0];
const familyName = arguments[1];
const password = arguments[2];

function isVisible(node) {
    if (!node) {
        return false;
    }
    const style = window.getComputedStyle(node);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
        return false;
    }
    const rect = node.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
}

function pickInput(selector) {
    return Array.from(document.querySelectorAll(selector)).find((node) => {
        return isVisible(node) && !node.disabled && !node.readOnly;
    }) || null;
}

function setInputValue(input, value) {
    if (!input) {
        return false;
    }
    input.focus();
    input.click();

    const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
    const tracker = input._valueTracker;
    if (tracker) {
        tracker.setValue('');
    }

    if (nativeSetter) {
        nativeSetter.call(input, '');
        nativeSetter.call(input, value);
    } else {
        input.value = '';
        input.value = value;
    }

    input.dispatchEvent(new InputEvent('beforeinput', {
        bubbles: true,
        cancelable: true,
        data: value,
        inputType: 'insertText',
    }));
    input.dispatchEvent(new InputEvent('input', {
        bubbles: true,
        cancelable: true,
        data: value,
        inputType: 'insertText',
    }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    input.dispatchEvent(new Event('blur', { bubbles: true }));

    return String(input.value || '') === String(value || '');
}

const givenInput = pickInput('input[data-testid="givenName"], input[name="givenName"], input[autocomplete="given-name"]');
const familyInput = pickInput('input[data-testid="familyName"], input[name="familyName"], input[autocomplete="family-name"]');
const passwordInput = pickInput('input[data-testid="password"], input[name="password"], input[type="password"]');

if (!givenInput || !familyInput || !passwordInput) {
    return 'not-ready';
}

const givenOk = setInputValue(givenInput, givenName);
const familyOk = setInputValue(familyInput, familyName);
const passwordOk = setInputValue(passwordInput, password);

if (!givenOk || !familyOk || !passwordOk) {
    return 'filled-failed';
}

return [
    String(givenInput.value || '').trim() === String(givenName || '').trim(),
    String(familyInput.value || '').trim() === String(familyName || '').trim(),
    String(passwordInput.value || '') === String(password || ''),
].every(Boolean) ? 'filled' : 'verify-failed';
            """,
            given_name,
            family_name,
            password,
        )

        if filled == "not-ready":
            sleep_with_cancel(0.5, cancel_callback)
            continue

        if filled != "filled":
            if log_callback:
                log_callback(
                    f"[Debug] 最终注册页输入框已出现，但姓名/密码写入失败: {filled}"
                )
            sleep_with_cancel(0.5, cancel_callback)
            continue

        values_ok = page.run_js(
            """
const expectedGiven = arguments[0];
const expectedFamily = arguments[1];
const expectedPassword = arguments[2];

function isVisible(node) {
    if (!node) {
        return false;
    }
    const style = window.getComputedStyle(node);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
        return false;
    }
    const rect = node.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
}

function pickInput(selector) {
    return Array.from(document.querySelectorAll(selector)).find((node) => {
        return isVisible(node) && !node.disabled && !node.readOnly;
    }) || null;
}

const givenInput = pickInput('input[data-testid="givenName"], input[name="givenName"], input[autocomplete="given-name"]');
const familyInput = pickInput('input[data-testid="familyName"], input[name="familyName"], input[autocomplete="family-name"]');
const passwordInput = pickInput('input[data-testid="password"], input[name="password"], input[type="password"]');

if (!givenInput || !familyInput || !passwordInput) {
    return false;
}

return String(givenInput.value || '').trim() === String(expectedGiven || '').trim()
    && String(familyInput.value || '').trim() === String(expectedFamily || '').trim()
    && String(passwordInput.value || '') === String(expectedPassword || '');
            """,
            given_name,
            family_name,
            password,
        )
        if not values_ok:
            if log_callback:
                log_callback("[Debug] 最终注册页字段值校验失败，继续重试填写。")
            sleep_with_cancel(0.5, cancel_callback)
            continue

        turnstile_state = page.run_js(
            """
const challengeInput = document.querySelector('input[name="cf-turnstile-response"]');
if (!challengeInput) {
    return 'not-found';
}
const value = String(challengeInput.value || '').trim();
return value ? 'ready' : 'pending';
            """
        )

        if turnstile_state == "pending" and not turnstile_token:
            if log_callback:
                log_callback(
                    "[*] 检测到最终注册页存在 Turnstile，开始使用现有真人化点击逻辑。"
                )
            turnstile_token = getTurnstileToken(log_callback, cancel_callback)
            if turnstile_token:
                synced = page.run_js(
                    """
const token = arguments[0];
const challengeInput = document.querySelector('input[name="cf-turnstile-response"]');
if (!challengeInput) {
    return false;
}
const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
if (nativeSetter) {
    nativeSetter.call(challengeInput, token);
} else {
    challengeInput.value = token;
}
challengeInput.dispatchEvent(new Event('input', { bubbles: true }));
challengeInput.dispatchEvent(new Event('change', { bubbles: true }));
return String(challengeInput.value || '').trim() === String(token || '').trim();
                    """,
                    turnstile_token,
                )
                if synced:
                    if log_callback:
                        log_callback("[*] Turnstile 响应已同步到最终注册表单。")

        sleep_with_cancel(1.2, cancel_callback)

        try:
            submit_button = page.ele("tag:button@@text()=完成注册")
        except Exception:
            submit_button = None

        if not submit_button:
            clicked = page.run_js(
                r"""
const challengeInput = document.querySelector('input[name="cf-turnstile-response"]');
if (challengeInput && !String(challengeInput.value || '').trim()) {
    return false;
}
const buttons = Array.from(document.querySelectorAll('button[type="submit"], button'));
const submitButton = buttons.find((node) => {
    const text = (node.innerText || node.textContent || '').replace(/\s+/g, '');
    return text === '完成注册' || text.includes('完成注册');
});
if (!submitButton || submitButton.disabled || submitButton.getAttribute('aria-disabled') === 'true') {
    return false;
}
submitButton.focus();
submitButton.click();
return true;
                """
            )
        else:
            challenge_value = page.run_js(
                """
const challengeInput = document.querySelector('input[name="cf-turnstile-response"]');
return challengeInput ? String(challengeInput.value || '').trim() : 'not-found';
                """
            )
            if challenge_value not in ("not-found", ""):
                submit_button.click()
                clicked = True
            else:
                clicked = False

        if clicked:
            if log_callback:
                log_callback(
                    f"[*] 已填写注册资料并点击完成注册: {given_name} {family_name} / {password}"
                )
            return {
                "given_name": given_name,
                "family_name": family_name,
                "password": password,
            }

        sleep_with_cancel(0.5, cancel_callback)

    raise Exception("未找到最终注册表单或完成注册按钮")


def get_current_sso_cookie():
    try:
        refresh_active_page()
        cookie_sources = []
        browser_obj = get_thread_browser()
        page_obj = get_thread_page()
        if browser_obj is not None:
            cookie_sources.append(browser_obj.cookies(all_info=True) or [])
        if page_obj is not None:
            cookie_sources.append(page_obj.cookies(all_domains=True, all_info=True) or [])
        for cookies in cookie_sources:
            for item in cookies:
                if isinstance(item, dict):
                    name = str(item.get("name", "")).strip()
                    value = str(item.get("value", "")).strip()
                else:
                    name = str(getattr(item, "name", "")).strip()
                    value = str(getattr(item, "value", "")).strip()
                if name == "sso" and value:
                    return value
    except Exception:
        return None
    return None


def iter_cookie_items():
    cookie_sources = []
    browser_obj = get_thread_browser()
    page_obj = get_thread_page()
    if browser_obj is not None:
        try:
            cookie_sources.append(browser_obj.cookies(all_info=True) or [])
        except Exception:
            pass
    if page_obj is not None:
        try:
            cookie_sources.append(page_obj.cookies(all_domains=True, all_info=True) or [])
        except Exception:
            pass
    for cookies in cookie_sources:
        for item in cookies:
            if isinstance(item, dict):
                name = str(item.get("name", "")).strip()
                value = str(item.get("value", "")).strip()
            else:
                name = str(getattr(item, "name", "")).strip()
                value = str(getattr(item, "value", "")).strip()
            yield name, value


def wait_for_sso_cookie(
    timeout=120,
    log_callback=None,
    cancel_callback=None,
):
    deadline = time.time() + timeout
    last_seen_names = set()

    while time.time() < deadline:
        raise_if_cancelled(cancel_callback)
        try:
            refresh_active_page()
            if get_thread_page() is None:
                sleep_with_cancel(1, cancel_callback)
                continue

            for name, value in iter_cookie_items():
                if name:
                    last_seen_names.add(name)

                if name == "sso" and value:
                    if log_callback:
                        log_callback("[*] 注册完成后已获取到 sso cookie。")
                    return value

        except PageDisconnectedError:
            refresh_active_page()
        except Exception:
            pass

        sleep_with_cancel(1, cancel_callback)

    raise Exception(
        f"注册完成后未获取到 sso cookie，当前已见 cookie: {sorted(last_seen_names)}"
    )


# ===================== GUI =====================
class GrokRegisterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Grok 注册机")
        self.root.geometry("680x650")

        self.is_running = False
        self.batch_count = 0
        self.success_count = 0
        self.fail_count = 0
        self.results = []
        self.stop_requested = False
        self.ui_queue = queue.Queue()
        self.state_lock = threading.Lock()

        self.setup_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def on_closing(self):
        self.stop_requested = True
        self.is_running = False
        quit_all_browsers()
        self.root.destroy()

    def setup_ui(self):
        load_config()

        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        config_frame = ttk.LabelFrame(main_frame, text="配置", padding=10)
        config_frame.pack(fill=tk.X, pady=5)

        ttk.Label(config_frame, text="邮箱服务商:").grid(row=0, column=0, sticky=tk.W)
        self.email_provider_var = tk.StringVar(
            value=config.get("email_provider", "duckmail")
        )
        self.email_provider_combo = ttk.Combobox(
            config_frame,
            textvariable=self.email_provider_var,
            values=["duckmail", "yyds", "cloudflare"],
            width=12,
            state="readonly",
        )
        self.email_provider_combo.grid(row=0, column=1, sticky=tk.W, padx=5)

        ttk.Label(config_frame, text="注册数量:").grid(
            row=0, column=2, sticky=tk.W, padx=10
        )
        self.count_var = tk.StringVar(value=str(config.get("register_count", 1)))
        self.count_spinbox = ttk.Spinbox(
            config_frame, from_=1, to=100, width=8, textvariable=self.count_var
        )
        self.count_spinbox.grid(row=0, column=3, sticky=tk.W, padx=5)

        self.nsfw_var = tk.BooleanVar(value=config.get("enable_nsfw", True))
        self.nsfw_check = ttk.Checkbutton(
            config_frame, text="注册后开启NSFW", variable=self.nsfw_var
        )
        self.nsfw_check.grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=5)

        ttk.Label(config_frame, text="并发线程数:").grid(
            row=1, column=2, sticky=tk.W, padx=10
        )
        self.concurrent_var = tk.StringVar(
            value=str(config.get("concurrent_workers", 1))
        )
        self.concurrent_spinbox = ttk.Spinbox(
            config_frame, from_=1, to=10, width=8, textvariable=self.concurrent_var
        )
        self.concurrent_spinbox.grid(row=1, column=3, sticky=tk.W, padx=5)

        ttk.Label(config_frame, text="代理 (可选):").grid(row=2, column=0, sticky=tk.W)
        self.proxy_var = tk.StringVar(value=config.get("proxy", ""))
        self.proxy_entry = ttk.Entry(
            config_frame, textvariable=self.proxy_var, width=30
        )
        self.proxy_entry.grid(row=2, column=1, columnspan=3, sticky=tk.W, padx=5)

        ttk.Label(config_frame, text="DuckMail API Key:").grid(
            row=3, column=0, sticky=tk.W
        )
        self.api_key_var = tk.StringVar(value=config.get("duckmail_api_key", ""))
        self.api_key_entry = ttk.Entry(
            config_frame, textvariable=self.api_key_var, width=30
        )
        self.api_key_entry.grid(row=3, column=1, columnspan=3, sticky=tk.W, padx=5)

        ttk.Label(config_frame, text="YYDS API Key:").grid(row=4, column=0, sticky=tk.W)
        self.yyds_api_key_var = tk.StringVar(value=config.get("yyds_api_key", ""))
        self.yyds_api_key_entry = ttk.Entry(
            config_frame, textvariable=self.yyds_api_key_var, width=30
        )
        self.yyds_api_key_entry.grid(row=4, column=1, columnspan=3, sticky=tk.W, padx=5)

        ttk.Label(config_frame, text="YYDS JWT:").grid(row=5, column=0, sticky=tk.W)
        self.yyds_jwt_var = tk.StringVar(value=config.get("yyds_jwt", ""))
        self.yyds_jwt_entry = ttk.Entry(
            config_frame, textvariable=self.yyds_jwt_var, width=30
        )
        self.yyds_jwt_entry.grid(row=5, column=1, columnspan=3, sticky=tk.W, padx=5)

        ttk.Label(config_frame, text="CF Mail API:").grid(row=6, column=0, sticky=tk.W)
        self.cfmail_api_base_var = tk.StringVar(value=config.get("cfmail_api_base", ""))
        self.cfmail_api_base_entry = ttk.Entry(
            config_frame, textvariable=self.cfmail_api_base_var, width=30
        )
        self.cfmail_api_base_entry.grid(row=6, column=1, columnspan=3, sticky=tk.W, padx=5)

        ttk.Label(config_frame, text="CF Admin 密码:").grid(row=7, column=0, sticky=tk.W)
        self.cfmail_admin_auth_var = tk.StringVar(value=config.get("cfmail_admin_auth", ""))
        self.cfmail_admin_auth_entry = ttk.Entry(
            config_frame, textvariable=self.cfmail_admin_auth_var, width=30, show="*"
        )
        self.cfmail_admin_auth_entry.grid(row=7, column=1, columnspan=3, sticky=tk.W, padx=5)

        ttk.Label(config_frame, text="CF 站点密码:").grid(row=8, column=0, sticky=tk.W)
        self.cfmail_custom_auth_var = tk.StringVar(value=config.get("cfmail_custom_auth", ""))
        self.cfmail_custom_auth_entry = ttk.Entry(
            config_frame, textvariable=self.cfmail_custom_auth_var, width=30, show="*"
        )
        self.cfmail_custom_auth_entry.grid(row=8, column=1, columnspan=3, sticky=tk.W, padx=5)

        ttk.Label(config_frame, text="CF 邮箱域名:").grid(row=9, column=0, sticky=tk.W)
        self.cfmail_domain_var = tk.StringVar(value=config.get("cfmail_domain", ""))
        self.cfmail_domain_entry = ttk.Entry(
            config_frame, textvariable=self.cfmail_domain_var, width=30
        )
        self.cfmail_domain_entry.grid(row=9, column=1, columnspan=3, sticky=tk.W, padx=5)

        self.cfmail_enable_prefix_var = tk.BooleanVar(
            value=config.get("cfmail_enable_prefix", False)
        )
        self.cfmail_enable_prefix_check = ttk.Checkbutton(
            config_frame, text="CF 使用 Worker 前缀", variable=self.cfmail_enable_prefix_var
        )
        self.cfmail_enable_prefix_check.grid(row=10, column=1, sticky=tk.W, pady=3)

        self.cfmail_enable_random_subdomain_var = tk.BooleanVar(
            value=config.get("cfmail_enable_random_subdomain", False)
        )
        self.cfmail_enable_random_subdomain_check = ttk.Checkbutton(
            config_frame,
            text="CF 随机二级域名",
            variable=self.cfmail_enable_random_subdomain_var,
        )
        self.cfmail_enable_random_subdomain_check.grid(row=10, column=2, columnspan=2, sticky=tk.W, pady=3)

        ttk.Label(
            config_frame,
            text="(需使用私有域名，请填JWT)",
            font=("Arial", 8),
            foreground="red",
        ).grid(row=11, column=1, columnspan=3, sticky=tk.W, padx=5)

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=10)

        self.start_btn = ttk.Button(
            btn_frame, text="开始注册", command=self.start_registration
        )
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = ttk.Button(
            btn_frame, text="停止", command=self.stop_registration, state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        self.clear_btn = ttk.Button(btn_frame, text="清空日志", command=self.clear_log)
        self.clear_btn.pack(side=tk.LEFT, padx=5)

        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=5)
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(status_frame, text="状态: ").pack(side=tk.LEFT)
        self.status_label = ttk.Label(
            status_frame, textvariable=self.status_var, foreground="green"
        )
        self.status_label.pack(side=tk.LEFT)

        self.stats_var = tk.StringVar(value="成功: 0 | 失败: 0")
        ttk.Label(status_frame, textvariable=self.stats_var).pack(side=tk.RIGHT)

        # 日志
        log_frame = ttk.LabelFrame(main_frame, text="日志", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=15, width=60)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.root.after(50, self._process_ui_queue)

    def _process_ui_queue(self):
        while True:
            try:
                callback, result, done = self.ui_queue.get_nowait()
            except queue.Empty:
                break

            try:
                value = callback()
                if result is not None:
                    result["value"] = value
            except Exception as exc:
                if result is not None:
                    result["error"] = exc
            finally:
                if done is not None:
                    done.set()

        try:
            self.root.after(50, self._process_ui_queue)
        except tk.TclError:
            pass

    def _call_in_ui(self, callback, wait=False):
        if threading.current_thread() is threading.main_thread():
            return callback()

        if not wait:
            self.ui_queue.put((callback, None, None))
            return None

        result = {"value": None, "error": None}
        done = threading.Event()
        self.ui_queue.put((callback, result, done))
        done.wait()

        if result["error"]:
            raise result["error"]
        return result["value"]

    def _set_running_ui_state(self, running, stopped=False):
        def apply():
            self.start_btn.config(state=tk.DISABLED if running else tk.NORMAL)
            self.stop_btn.config(state=tk.NORMAL if running else tk.DISABLED)
            if running:
                self.status_var.set("运行中...")
                self.status_label.config(foreground="blue")
            else:
                self.status_var.set("已停止" if stopped else "完成")
                self.status_label.config(foreground="orange" if stopped else "green")

        self._call_in_ui(apply)

    def _show_info(self, title, message):
        self._call_in_ui(lambda: messagebox.showinfo(title, message))

    def log(self, message):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")

        def append():
            self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
            self.log_text.see(tk.END)

        self._call_in_ui(append)

    def clear_log(self):
        self._call_in_ui(lambda: self.log_text.delete(1.0, tk.END))

    def update_stats(self):
        self._call_in_ui(
            lambda: self.stats_var.set(
                f"成功: {self.success_count} | 失败: {self.fail_count}"
            )
        )

    def should_stop(self):
        return self.stop_requested or not self.is_running

    def start_registration(self):
        if self.is_running:
            return

        try:
            count = int(self.count_var.get())
        except ValueError:
            messagebox.showerror("错误", "请输入有效的注册数量")
            return

        try:
            concurrent_workers = int(self.concurrent_var.get())
        except ValueError:
            messagebox.showerror("错误", "请输入有效的并发线程数")
            return

        concurrent_workers = max(1, min(concurrent_workers, count, 10))

        config["register_count"] = count
        config["concurrent_workers"] = concurrent_workers
        config["proxy"] = self.proxy_var.get().strip()
        config["duckmail_api_key"] = self.api_key_var.get().strip()
        config["yyds_api_key"] = self.yyds_api_key_var.get().strip()
        config["yyds_jwt"] = self.yyds_jwt_var.get().strip()
        config["cfmail_api_base"] = self.cfmail_api_base_var.get().strip().rstrip("/")
        config["cfmail_admin_auth"] = self.cfmail_admin_auth_var.get().strip()
        config["cfmail_custom_auth"] = self.cfmail_custom_auth_var.get().strip()
        config["cfmail_domain"] = self.cfmail_domain_var.get().strip()
        config["cfmail_enable_prefix"] = self.cfmail_enable_prefix_var.get()
        config["cfmail_enable_random_subdomain"] = (
            self.cfmail_enable_random_subdomain_var.get()
        )
        config["enable_nsfw"] = self.nsfw_var.get()
        config["email_provider"] = self.email_provider_var.get()

        if config["email_provider"] == "yyds" and not (
            config["yyds_api_key"] or config["yyds_jwt"]
        ):
            messagebox.showerror("错误", "使用 YYDS 时，请至少填写 API Key 或 JWT")
            return

        if config["email_provider"] == "cloudflare" and not (
            config["cfmail_api_base"] and config["cfmail_admin_auth"]
        ):
            messagebox.showerror(
                "错误",
                "使用 Cloudflare 时，请填写 CF Mail API 和 CF Admin 密码",
            )
            return

        save_config()

        self.is_running = True
        self.stop_requested = False
        self.batch_count += 1
        self.success_count = 0
        self.fail_count = 0
        self.results = []

        self._set_running_ui_state(True)

        self.log(
            f"========== 开始第 {self.batch_count} 批注册 (共 {count} 个) =========="
        )

        # 启动线程
        self.log(f"[*] 并发线程数: {concurrent_workers}")

        thread = threading.Thread(
            target=self.run_registration,
            args=(count, config["enable_nsfw"], concurrent_workers),
            daemon=True,
        )
        thread.start()

    def stop_registration(self):
        self.stop_requested = True
        self.is_running = False
        self.log("[!] 用户停止注册")

    def run_registration_sequential_legacy(self, count, enable_nsfw):
        stopped_early = False

        try:
            start_browser()
            self.log("[*] 浏览器已启动")

            for i in range(count):
                if self.should_stop():
                    stopped_early = True
                    break

                self.log(f"\n--- 开始注册第 {i + 1}/{count} 个账号 ---")

                try:
                    # 注册流程
                    self.log("[*] 1. 打开注册页...")
                    open_signup_page(
                        log_callback=self.log, cancel_callback=self.should_stop
                    )
                    self.log("[*] 2. 填写邮箱...")
                    email, dev_token = fill_email_and_submit(
                        log_callback=self.log, cancel_callback=self.should_stop
                    )
                    self.log("[*] 3. 填写验证码...")
                    fill_code_and_submit(
                        email,
                        dev_token,
                        log_callback=self.log,
                        cancel_callback=self.should_stop,
                    )
                    self.log("[*] 4. 填写资料...")
                    profile = fill_profile_and_submit(
                        log_callback=self.log, cancel_callback=self.should_stop
                    )
                    self.log("[*] 5. 获取sso cookie...")
                    sso = wait_for_sso_cookie(
                        log_callback=self.log,
                        cancel_callback=self.should_stop,
                    )

                    result = {
                        "email": email,
                        "sso": sso,
                        "password": profile["password"],
                        "given_name": profile["given_name"],
                        "family_name": profile["family_name"],
                    }
                    self.results.append(result)

                    # 开启NSFW
                    if enable_nsfw:
                        self.log("[*] 正在开启NSFW...")
                        success, msg = enable_nsfw_for_token(sso, log_callback=self.log)
                        if success:
                            self.log(f"[+] {msg}")
                        else:
                            self.log(f"[-] {msg}")

                    self.success_count += 1
                    self.log(f"[+] 注册成功: {email}")

                except RegistrationCancelled as e:
                    stopped_early = True
                    self.log(f"[!] {str(e)}")
                    break
                except Exception as e:
                    self.fail_count += 1
                    self.log(f"[-] 注册失败: {format_exception_for_log(e)}")

                finally:
                    if self.should_stop():
                        stop_browser()
                    else:
                        self.log("[*] 重启浏览器，下一轮会清空登录态...")
                        restart_browser()
                    self.update_stats()

                if i < count - 1 and not self.should_stop():
                    sleep_with_cancel(2, self.should_stop)

        except RegistrationCancelled as e:
            stopped_early = True
            self.log(f"[!] {str(e)}")
        except Exception as e:
            self.log(f"[!] 错误: {format_exception_for_log(e)}")

        finally:
            stop_browser()
            stopped = self.stop_requested or stopped_early
            self.save_results(stopped=stopped)
            self.is_running = False
            self._set_running_ui_state(False, stopped=stopped)
            self.log(
                f"\n========== 本批注册{'已停止' if stopped else '完成'}: 成功 {self.success_count}, 失败 {self.fail_count} =========="
            )

    def run_registration(self, count, enable_nsfw, concurrent_workers=1):
        stopped_early = False
        workers = max(1, min(int(concurrent_workers or 1), count))

        try:
            self.log(f"[*] 启动 {workers} 个并发注册任务")
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [
                    executor.submit(
                        self.run_registration_task, i + 1, count, enable_nsfw
                    )
                    for i in range(count)
                ]

                for future in as_completed(futures):
                    try:
                        status = future.result()
                    except Exception as exc:
                        with self.state_lock:
                            self.fail_count += 1
                        self.log(f"[-] 注册任务异常: {format_exception_for_log(exc)}")
                        self.update_stats()
                        continue

                    if status == "stopped":
                        stopped_early = True

        except RegistrationCancelled as e:
            stopped_early = True
            self.log(f"[!] {str(e)}")
        except Exception as e:
            self.log(f"[!] 错误: {format_exception_for_log(e)}")

        finally:
            stopped = self.stop_requested or stopped_early
            self.save_results(stopped=stopped)
            self.is_running = False
            self._set_running_ui_state(False, stopped=stopped)
            self.log(
                f"\n========== 本批注册{'已停止' if stopped else '完成'}: 成功 {self.success_count}, 失败 {self.fail_count} =========="
            )

    def run_registration_task(self, index, total, enable_nsfw):
        if self.should_stop():
            return "stopped"

        prefix = f"[{index}/{total}]"

        def task_log(message):
            self.log(f"{prefix} {message}")

        task_log("开始注册账号")

        try:
            start_browser()
            task_log("浏览器已启动")

            task_log("1. 打开注册页...")
            open_signup_page(log_callback=task_log, cancel_callback=self.should_stop)

            task_log("2. 填写邮箱...")
            email, dev_token = fill_email_and_submit(
                log_callback=task_log, cancel_callback=self.should_stop
            )

            task_log("3. 填写验证码...")
            fill_code_and_submit(
                email,
                dev_token,
                log_callback=task_log,
                cancel_callback=self.should_stop,
            )

            task_log("4. 填写资料...")
            profile = fill_profile_and_submit(
                log_callback=task_log, cancel_callback=self.should_stop
            )

            task_log("5. 获取 sso cookie...")
            sso = wait_for_sso_cookie(
                log_callback=task_log,
                cancel_callback=self.should_stop,
            )

            result = {
                "email": email,
                "sso": sso,
                "password": profile["password"],
                "given_name": profile["given_name"],
                "family_name": profile["family_name"],
            }

            if enable_nsfw:
                task_log("正在开启 NSFW...")
                success, msg = enable_nsfw_for_token(sso, log_callback=task_log)
                task_log(f"[+] {msg}" if success else f"[-] {msg}")

            with self.state_lock:
                self.results.append(result)
                self.success_count += 1
            self.update_stats()
            task_log(f"[+] 注册成功: {email}")
            return "success"

        except RegistrationCancelled as e:
            task_log(f"[!] {str(e)}")
            return "stopped"
        except Exception as e:
            with self.state_lock:
                self.fail_count += 1
            self.update_stats()
            task_log(f"[-] 注册失败: {format_exception_for_log(e)}")
            return "failed"
        finally:
            stop_browser()

    def save_results(self, stopped=False):
        if not self.results:
            return

        # 文件名格式: date_time_times.txt
        now = datetime.datetime.now()
        filename = f"{now.strftime('%Y.%m.%d_%H.%M')}_{self.batch_count}.txt"

        seen_sso = set()
        duplicate_count = 0
        with open(filename, "w", encoding="utf-8") as f:
            for r in self.results:
                sso = str(r.get("sso", "")).strip()
                if not sso:
                    continue
                if sso in seen_sso:
                    duplicate_count += 1
                    continue
                seen_sso.add(sso)
                f.write(f"{sso}\n")

        if duplicate_count:
            self.log(f"[!] 已跳过 {duplicate_count} 条重复 sso，结果文件只保留唯一登录信息")

        self.log(f"[*] 结果已保存到: {filename}")
        title = "已停止" if stopped else "完成"
        message = "注册已停止，已保存当前结果。" if stopped else "注册完成!"
        self._show_info(title, f"{message}\n结果已保存到: {filename}")


def main():
    start_async_clean()
    root = tk.Tk()
    app = GrokRegisterGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()

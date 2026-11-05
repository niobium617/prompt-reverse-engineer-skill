#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""受限 URL 下载（prompt-reverse-engineer 技能组件）。

安全边界：
  - 仅允许 http / https；
  - 拒绝带用户名/密码的 URL；
  - 域名解析出的所有地址必须是公网地址，拒绝回环、私网、链路本地、
    站点本地（fec0::/10）、保留、组播与未指定地址（含 169.254.169.254
    等云元数据端）；IPv4 映射 IPv6 地址按 Python 的分类规则同样拒绝；
  - 手动跟随重定向，每一跳都重新校验，最多 5 跳；
  - 流式读取并限制总字节数，超限立即中止。

已知限制：DNS 在校验与实际连接之间可能被重新解析（DNS rebinding），
本模块只能保证「校验时」的地址安全；需要更强保证时应改接出口代理。
"""
import ipaddress
import socket
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import BaseHandler, Request, build_opener

MAX_REDIRECTS = 5
CHUNK = 64 * 1024
REDIRECT_CODES = (301, 302, 303, 307, 308)
USER_AGENT = "prompt-reverse-engineer/2.0 (+local-skill)"


class DownloadError(Exception):
    """URL 校验或下载失败。"""


class _NoRedirectHandler(BaseHandler):
    """禁用自动重定向：3xx 由 urllib 抛 HTTPError，交给 fetch_url 逐跳校验。"""

    handler_order = 400  # 先于 HTTPErrorProcessor(1000)

    def http_error_301(self, req, fp, code, msg, headers):
        return None

    http_error_302 = http_error_303 = http_error_307 = http_error_308 = http_error_301


def _is_public_ip(value):
    try:
        addr = ipaddress.ip_address(str(value).split("%", 1)[0])
    except ValueError:
        return False
    return not (
        addr.is_private or addr.is_loopback or addr.is_link_local
        or getattr(addr, "is_site_local", False)
        or addr.is_reserved or addr.is_multicast or addr.is_unspecified
    )


def validate_url(url):
    """校验协议、主机与解析地址；通过则返回原 URL，否则抛 DownloadError。"""
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise DownloadError(f"URL 解析失败：{exc}") from exc
    if parts.scheme not in ("http", "https"):
        raise DownloadError("仅支持 http / https URL")
    if not parts.hostname:
        raise DownloadError("URL 缺少主机名")
    if parts.username or parts.password:
        raise DownloadError("URL 不允许携带用户名或密码")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise DownloadError(f"URL 端口非法：{exc}") from exc

    host = parts.hostname
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise DownloadError(f"域名无法解析：{host}（{exc}）") from exc
    addresses = sorted({info[4][0] for info in infos})
    if not addresses:
        raise DownloadError(f"域名无可用地址：{host}")
    blocked = [ip for ip in addresses if not _is_public_ip(ip)]
    if blocked:
        raise DownloadError(f"目标地址不在公网范围，已拒绝：{host} -> {', '.join(blocked)}")
    return url


def _read_limited(resp, max_bytes):
    chunks, total = [], 0
    while True:
        chunk = resp.read(CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise DownloadError(f"响应超过大小上限 {max_bytes} 字节")
        chunks.append(chunk)
    return b"".join(chunks)


def fetch_url(url, timeout=15.0, max_bytes=64 * 1024 * 1024):
    """下载 URL 内容；任何不安全或超限情况抛 DownloadError。"""
    if max_bytes is None or max_bytes <= 0:
        raise DownloadError("max_bytes 必须为正数")
    current = url
    opener = build_opener(_NoRedirectHandler)
    for hop in range(MAX_REDIRECTS + 1):
        validate_url(current)
        request = Request(current, headers={
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "identity",
        })
        try:
            with opener.open(request, timeout=timeout) as resp:
                return _read_limited(resp, max_bytes)
        except HTTPError as exc:
            location = exc.headers.get("Location")
            if exc.code in REDIRECT_CODES and location:
                if hop >= MAX_REDIRECTS:
                    raise DownloadError(f"重定向超过 {MAX_REDIRECTS} 次") from exc
                current = urljoin(current, location)
                continue
            raise DownloadError(f"HTTP {exc.code}：{exc.reason}") from exc
        except (URLError, OSError, ValueError) as exc:
            raise DownloadError(str(exc)) from exc
    raise DownloadError(f"重定向超过 {MAX_REDIRECTS} 次")


if __name__ == "__main__":  # 便于手工自检：python _net.py <url>
    if len(sys.argv) != 2:
        print("用法：python _net.py <url>", file=sys.stderr)
        sys.exit(1)
    try:
        data = fetch_url(sys.argv[1], max_bytes=32 * 1024 * 1024)
    except DownloadError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(3)
    print(f"OK：{len(data)} 字节")

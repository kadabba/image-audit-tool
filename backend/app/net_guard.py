"""Защита от SSRF: не выпускаем запросы во внутреннюю сеть."""

import ipaddress
import socket
from urllib.parse import urlparse


def _is_internal(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def check_public_url(url: str) -> None:
    """Бросает ValueError, если URL ведёт не на публичный http(s)-адрес."""
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError("Разрешены только http и https")
    if not parsed.hostname:
        raise ValueError("URL без хоста")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(parsed.hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValueError("Не удалось разрешить имя хоста")

    # ponytail: резолвим и проверяем; от DNS-rebinding не спасёт,
    # для этого нужен свой connector с пиннингом IP — если понадобится
    for info in infos:
        if _is_internal(info[4][0]):
            raise ValueError("Обращение к внутренним адресам запрещено")


def demo():
    for bad in ("http://localhost/x", "http://127.0.0.1/x", "http://169.254.169.254/",
                "file:///etc/passwd", "http://10.0.0.1/x", "http://[::1]/x"):
        try:
            check_public_url(bad)
            raise AssertionError(f"должен был отклонить: {bad}")
        except ValueError:
            pass

    check_public_url("https://example.com/img.png")  # публичный — проходит
    print("net_guard: ok")


if __name__ == "__main__":
    demo()

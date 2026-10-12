"""Reject non-public browser destinations; deployment still needs network isolation."""
import ipaddress
import socket
from urllib.parse import urlsplit


def require_public_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Only public HTTP(S) URLs without credentials are supported')
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError('Private or reserved network destinations are blocked')

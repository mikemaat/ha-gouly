"""Find a Gouly controller on the local network.

Gouly controllers don't broadcast Tuya discovery packets, but only the real controller
can decrypt a session made with its local key. We look for hosts with the Tuya port open
and try the key on each one.

This module is shared with the gouly-keys tool, so it must not import Home Assistant.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor

import tinytuya

TUYA_PORT = 6668
PROTOCOL_VERSIONS = (3.5, 3.4, 3.3)


def guess_local_networks() -> list[ipaddress.IPv4Network]:
    """Best-effort list of the private /24 networks this machine is connected to."""
    addresses: set[str] = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))  # no packets are sent for UDP connect
            addresses.add(sock.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addresses.add(str(info[4][0]))
    except OSError:
        pass
    return networks_for_addresses(addresses)


def networks_for_addresses(addresses: Iterable[str], prefix: int = 24) -> list[ipaddress.IPv4Network]:
    """Turn interface addresses into the private networks to scan (capped at /24)."""
    networks: list[ipaddress.IPv4Network] = []
    for address in addresses:
        ip = ipaddress.IPv4Address(address)
        if ip.is_loopback or ip.is_link_local or not ip.is_private:
            continue
        network = ipaddress.IPv4Network(f"{ip}/{max(prefix, 24)}", strict=False)
        if network not in networks:
            networks.append(network)
    return networks


def _port_open(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def find_tuya_hosts(
    networks: Iterable[ipaddress.IPv4Network],
    port: int = TUYA_PORT,
    timeout: float = 3.0,
    workers: int = 32,
) -> list[str]:
    """Return hosts with the Tuya local port open.

    Gouly controllers respond slowly, so keep concurrency moderate and timeouts generous;
    an aggressive scan misses them.
    """
    hosts = [str(ip) for network in networks for ip in network.hosts()]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = pool.map(lambda h: (h, _port_open(h, port, timeout)), hosts)
        return [host for host, is_open in results if is_open]


def probe(
    host: str,
    device_id: str,
    local_key: str,
    versions: Iterable[float] = PROTOCOL_VERSIONS,
    timeout: float = 5.0,
) -> float | None:
    """Return the protocol version if `host` accepts this device ID and key, else None."""
    for version in versions:
        device = tinytuya.Device(
            device_id,
            host,
            local_key,
            version=version,
            connection_timeout=timeout,
            connection_retry_limit=1,
        )
        try:
            status = device.status()
        except Exception:  # noqa: BLE001 - tinytuya raises a variety of errors
            status = None
        finally:
            device.close()
        if isinstance(status, dict) and "dps" in status:
            return version
    return None


def discover(
    device_id: str,
    local_key: str,
    networks: Iterable[ipaddress.IPv4Network] | None = None,
    candidates: Iterable[str] | None = None,
) -> tuple[str, float] | None:
    """Find the controller for this device ID and key. Returns (host, protocol version)."""
    hosts = list(candidates) if candidates is not None else None
    if hosts is None:
        hosts = find_tuya_hosts(networks if networks is not None else guess_local_networks())
    for host in hosts:
        version = probe(host, device_id, local_key)
        if version is not None:
            return host, version
    return None

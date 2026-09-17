"""Discovery helper tests (no network access)."""

import ipaddress

from gouly_core import discovery


def test_networks_for_addresses_filters_and_dedupes() -> None:
    networks = discovery.networks_for_addresses(
        ["192.168.1.20", "192.168.1.30", "127.0.0.1", "169.254.1.2", "100.100.1.1", "8.8.8.8", "10.1.2.3"]
    )
    assert networks == [ipaddress.IPv4Network("192.168.1.0/24"), ipaddress.IPv4Network("10.1.2.0/24")]


def test_discover_tries_candidates_in_order(monkeypatch) -> None:
    tried = []

    def fake_probe(host, device_id, local_key):
        tried.append(host)
        return 3.5 if host == "192.168.1.50" else None

    monkeypatch.setattr(discovery, "probe", fake_probe)
    assert discovery.discover("dev", "k" * 16, candidates=["192.168.1.5", "192.168.1.50", "192.168.1.9"]) == (
        "192.168.1.50",
        3.5,
    )
    assert tried == ["192.168.1.5", "192.168.1.50"]

"""Unit tests for the DNS provider."""

from __future__ import annotations

import io
import json
from urllib.request import Request

import pytest

from infrakit.core.session import AWSSession
from infrakit.providers.dns import DNSProvider
from infrakit.schema.models import DNSResource


@pytest.fixture()
def route53_zone(mocked_aws: None) -> str:
    client = AWSSession.client("route53", region_name="us-east-1")
    resp = client.create_hosted_zone(
        Name="example.com",
        CallerReference="infrakit-test-zone",
    )
    return str(resp["HostedZone"]["Id"]).split("/")[-1]


def _make_route53_provider(route53_zone: str) -> DNSProvider:
    cfg = DNSResource(
        type="dns",
        provider="route53",
        zone="example.com",
        record="api",
        target="service.example.net",
        record_type="CNAME",
        ttl=300,
    )
    return DNSProvider("api_dns", cfg, project="proj", env="dev")


class TestRoute53DNSProvider:
    def test_create_exists_delete_flow(self, mocked_aws: None, route53_zone: str) -> None:
        provider = _make_route53_provider(route53_zone)

        assert provider.exists() is False
        outputs = provider.create()
        assert outputs["provider"] == "route53"
        assert outputs["record"] == "api.example.com"

        assert provider.exists() is True
        provider.delete()
        assert provider.exists() is False

    def test_route53_alias_record(self, mocked_aws: None, route53_zone: str) -> None:
        cfg = DNSResource(
            type="dns",
            provider="route53",
            zone="example.com",
            record="@",
            target="my-alb-123.us-east-1.elb.amazonaws.com",
            record_type="A",
            alias=True,
            target_hosted_zone_id="Z35SXDOTRQ7X7K",
        )
        provider = DNSProvider("root_dns", cfg, project="proj", env="dev")
        provider.create()
        assert provider.exists() is True


class _HTTPResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._raw = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def read(self) -> bytes:
        return self._raw.read()

    def __enter__(self) -> _HTTPResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


def _seed_cloudflare_token_secret() -> None:
    secrets = AWSSession.client("secretsmanager", region_name="us-east-1")
    secrets.create_secret(Name="/proj/cloudflare-token", SecretString="cf-token")


class TestCloudflareDNSProvider:
    def test_create_exists_delete_flow(
        self, mocked_aws: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_cloudflare_token_secret()

        records: dict[str, dict[str, object]] = {}

        def fake_urlopen(req: Request, timeout: int = 15) -> _HTTPResponse:
            method = req.get_method()
            url = req.full_url

            if "zones?name=example.com" in url:
                return _HTTPResponse({"success": True, "result": [{"id": "zone-1"}]})

            if "dns_records?name=api.example.com&type=CNAME" in url:
                result = list(records.values())
                return _HTTPResponse({"success": True, "result": result})

            if url.endswith("/zones/zone-1/dns_records") and method == "POST":
                body = json.loads((req.data or b"{}").decode("utf-8"))
                records["rec-1"] = {
                    "id": "rec-1",
                    "content": body["content"],
                    "proxied": body.get("proxied"),
                }
                return _HTTPResponse({"success": True, "result": records["rec-1"]})

            if url.endswith("/zones/zone-1/dns_records/rec-1") and method == "PUT":
                body = json.loads((req.data or b"{}").decode("utf-8"))
                records["rec-1"]["content"] = body["content"]
                records["rec-1"]["proxied"] = body.get("proxied")
                return _HTTPResponse({"success": True, "result": records["rec-1"]})

            if url.endswith("/zones/zone-1/dns_records/rec-1") and method == "DELETE":
                records.clear()
                return _HTTPResponse({"success": True, "result": {}})

            raise AssertionError(f"Unexpected request: {method} {url}")

        monkeypatch.setattr("infrakit.providers.dns.urlopen", fake_urlopen)

        cfg = DNSResource(
            type="dns",
            provider="cloudflare",
            zone="example.com",
            record="api",
            target="https://service.example.net/health",
            record_type="CNAME",
            proxied=True,
        )
        provider = DNSProvider("cf_dns", cfg, project="proj", env="dev")

        assert provider.exists() is False
        outputs = provider.create()
        assert outputs["provider"] == "cloudflare"
        assert outputs["target"] == "service.example.net"
        assert provider.exists() is True

        provider.delete()
        assert provider.exists() is False

"""DNS provider for Route53 and Cloudflare."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from botocore.exceptions import ClientError

from infrakit.core.session import AWSSession
from infrakit.providers.base import ResourceProvider
from infrakit.schema.models import DNSResource


@dataclass
class _CloudflareRecord:
    record_id: str
    content: str
    proxied: bool | None


class DNSProvider(ResourceProvider):
    config: DNSResource

    def __init__(
        self,
        name: str,
        config: DNSResource,
        project: str,
        env: str,
        region: str = "us-east-1",
    ) -> None:
        super().__init__(name, config, project, env, region)
        self._route53 = AWSSession.client("route53", region_name=region)
        self._secrets = AWSSession.client("secretsmanager", region_name=region)

    def exists(self) -> bool:
        cfg = self.config
        if cfg.provider == "route53":
            return self._route53_record_matches()
        return self._cloudflare_record_matches()

    def create(self) -> dict[str, Any]:
        cfg = self.config
        if cfg.provider == "route53":
            self._upsert_route53_record()
        else:
            self._upsert_cloudflare_record()

        return {
            "provider": cfg.provider,
            "zone": cfg.zone,
            "record": self._record_fqdn,
            "record_type": cfg.record_type,
            "target": self._record_target,
        }

    def delete(self) -> None:
        cfg = self.config
        if cfg.provider == "route53":
            self._delete_route53_record()
            return
        self._delete_cloudflare_record()

    @property
    def _record_fqdn(self) -> str:
        cfg = self.config
        record = cfg.record.strip()
        if record in ("", "@"):
            return cfg.zone
        if record.endswith(f".{cfg.zone}"):
            return record
        return f"{record}.{cfg.zone}"

    @property
    def _record_target(self) -> str:
        cfg = self.config
        if cfg.record_type == "TXT":
            return cfg.target

        raw = cfg.target.strip().rstrip(".")
        parsed = urlparse(raw)
        if parsed.scheme and parsed.hostname:
            return parsed.hostname
        return raw

    # ------------------------------------------------------------------
    # Route53
    # ------------------------------------------------------------------

    def _route53_record_matches(self) -> bool:
        record = self._get_route53_record_set()
        if record is None:
            return False

        cfg = self.config
        if cfg.alias:
            alias_raw = record.get("AliasTarget")
            if not isinstance(alias_raw, dict):
                return False
            alias = cast(dict[str, Any], alias_raw)
            dns_name = str(alias.get("DNSName", "")).rstrip(".")
            hosted_zone_id = str(alias.get("HostedZoneId", ""))
            return bool(
                dns_name == self._record_target and hosted_zone_id == cfg.target_hosted_zone_id
            )

        values = [r["Value"].strip('"').rstrip(".") for r in record.get("ResourceRecords", [])]
        return len(values) == 1 and values[0] == self._record_target

    def _upsert_route53_record(self) -> None:
        zone_id = self._get_route53_zone_id()
        cfg = self.config
        if cfg.alias:
            record_set: dict[str, Any] = {
                "Name": self._record_fqdn,
                "Type": "A",
                "AliasTarget": {
                    "DNSName": self._record_target,
                    "HostedZoneId": cfg.target_hosted_zone_id,
                    "EvaluateTargetHealth": cfg.evaluate_target_health,
                },
            }
        else:
            value = self._record_target
            if cfg.record_type == "TXT" and not value.startswith('"'):
                value = f'"{value}"'

            record_set = {
                "Name": self._record_fqdn,
                "Type": cfg.record_type,
                "TTL": cfg.ttl,
                "ResourceRecords": [{"Value": value}],
            }

        self._route53.change_resource_record_sets(
            HostedZoneId=zone_id,
            ChangeBatch={
                "Changes": [
                    {
                        "Action": "UPSERT",
                        "ResourceRecordSet": record_set,
                    }
                ]
            },
        )

    def _delete_route53_record(self) -> None:
        zone_id = self._get_route53_zone_id()
        record = self._get_route53_record_set()
        if record is None:
            return
        self._route53.change_resource_record_sets(
            HostedZoneId=zone_id,
            ChangeBatch={
                "Changes": [
                    {
                        "Action": "DELETE",
                        "ResourceRecordSet": record,
                    }
                ]
            },
        )

    def _get_route53_zone_id(self) -> str:
        dns_name = f"{self.config.zone}."
        resp = self._route53.list_hosted_zones_by_name(DNSName=dns_name, MaxItems="1")
        zones = resp.get("HostedZones", [])
        for zone in zones:
            if zone["Name"].rstrip(".") == self.config.zone:
                return str(zone["Id"]).split("/")[-1]
        raise ValueError(f"Route53 hosted zone '{self.config.zone}' not found in this AWS account.")

    def _get_route53_record_set(self) -> dict[str, Any] | None:
        zone_id = self._get_route53_zone_id()
        resp = self._route53.list_resource_record_sets(
            HostedZoneId=zone_id,
            StartRecordName=self._record_fqdn,
            StartRecordType=self.config.record_type,
            MaxItems="1",
        )
        records = resp.get("ResourceRecordSets", [])
        if not records:
            return None
        record = records[0]
        if (
            record["Name"].rstrip(".") != self._record_fqdn
            or record["Type"] != self.config.record_type
        ):
            return None
        return dict(record)

    # ------------------------------------------------------------------
    # Cloudflare
    # ------------------------------------------------------------------

    def _cloudflare_record_matches(self) -> bool:
        record = self._find_cloudflare_record()
        if record is None:
            return False
        cfg = self.config
        target = self._record_target
        if record.content.rstrip(".") != target:
            return False
        if cfg.record_type in ("A", "AAAA", "CNAME") and record.proxied is not None:
            return record.proxied == cfg.proxied
        return True

    def _upsert_cloudflare_record(self) -> None:
        cfg = self.config
        zone_id = self._get_cloudflare_zone_id()
        record = self._find_cloudflare_record()
        payload: dict[str, Any] = {
            "type": cfg.record_type,
            "name": self._record_fqdn,
            "content": self._record_target,
            "ttl": cfg.ttl,
        }
        if cfg.record_type in ("A", "AAAA", "CNAME"):
            payload["proxied"] = cfg.proxied

        if record is None:
            self._cloudflare_request(
                "POST",
                f"/zones/{zone_id}/dns_records",
                payload,
            )
            return

        self._cloudflare_request(
            "PUT",
            f"/zones/{zone_id}/dns_records/{record.record_id}",
            payload,
        )

    def _delete_cloudflare_record(self) -> None:
        zone_id = self._get_cloudflare_zone_id()
        record = self._find_cloudflare_record()
        if record is None:
            return
        self._cloudflare_request(
            "DELETE",
            f"/zones/{zone_id}/dns_records/{record.record_id}",
            None,
        )

    def _get_cloudflare_zone_id(self) -> str:
        zone = self.config.zone
        resp = self._cloudflare_request("GET", f"/zones?name={zone}", None)
        zones = resp.get("result", [])
        if not zones:
            raise ValueError(f"Cloudflare zone '{zone}' not found for provided API token.")
        return str(zones[0]["id"])

    def _find_cloudflare_record(self) -> _CloudflareRecord | None:
        zone_id = self._get_cloudflare_zone_id()
        name = self._record_fqdn
        rtype = self.config.record_type
        resp = self._cloudflare_request(
            "GET",
            f"/zones/{zone_id}/dns_records?name={name}&type={rtype}",
            None,
        )
        records = resp.get("result", [])
        if not records:
            return None
        data = records[0]
        return _CloudflareRecord(
            record_id=str(data["id"]),
            content=str(data["content"]),
            proxied=data.get("proxied"),
        )

    def _cloudflare_token(self) -> str:
        secret_name = self.config.cloudflare_token_secret or f"/{self.project}/cloudflare-token"
        try:
            response = self._secrets.get_secret_value(SecretId=secret_name)
        except ClientError as exc:
            raise ValueError(
                f"Cloudflare API token secret '{secret_name}' not found or not accessible."
            ) from exc

        token = response.get("SecretString")
        if not token:
            raise ValueError(f"Cloudflare token secret '{secret_name}' has no SecretString value.")
        return str(token).strip()

    def _cloudflare_request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        base_url = "https://api.cloudflare.com/client/v4"
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{base_url}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self._cloudflare_token()}",
                "Content-Type": "application/json",
            },
        )

        try:
            with urlopen(request, timeout=15) as response:  # noqa: S310
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"Cloudflare API request failed ({exc.code}): {exc.reason}") from exc

        if not isinstance(data, dict):
            raise RuntimeError("Cloudflare API request failed: malformed JSON response.")
        if not bool(data.get("success", True)):
            errors = data.get("errors", [])
            raise RuntimeError(f"Cloudflare API request failed: {errors!r}")
        return cast(dict[str, Any], data)

"""Integration tests for DNS resource lifecycle via engine."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import boto3
import pytest

from infrakit.core.engine import Engine
from infrakit.schema.validator import load_config


@pytest.fixture()
def dns_config(tmp_path: Path) -> Path:
    cfg_file = tmp_path / "infrakit.yaml"
    cfg_file.write_text(
        textwrap.dedent(f"""\
            project: dns-integ
            region: us-east-1
            env: dev

            state:
              backend: local
              path: {tmp_path}/.infrakit/state.json

            services:
              app_dns:
                type: dns
                provider: route53
                zone: sokech.com
                record: example
                record_type: CNAME
                target: app-v2.internal.example.net
                ttl: 300
        """),
        encoding="utf-8",
    )
    return cfg_file


def _record(
    client: Any,
    zone_id: str,
    name: str = "example.sokech.com",
    rtype: str = "CNAME",
) -> dict[str, Any] | None:
    resp = client.list_resource_record_sets(
        HostedZoneId=zone_id,
        StartRecordName=name,
        StartRecordType=rtype,
        MaxItems="1",
    )
    records = resp.get("ResourceRecordSets", [])
    if not records:
        return None
    record = records[0]
    if record["Name"].rstrip(".") != name or record["Type"] != rtype:
        return None
    return dict(record)


class TestDNSFlow:
    def test_dns_deploy_and_destroy(self, mocked_aws: None, dns_config: Path) -> None:
        route53 = boto3.client("route53", region_name="us-east-1")
        zone = route53.create_hosted_zone(Name="sokech.com", CallerReference="dns-flow-destroy")
        zone_id = zone["HostedZone"]["Id"].split("/")[-1]

        cfg = load_config(dns_config)
        engine = Engine(cfg)
        engine.deploy(auto_approve=True)

        record = _record(route53, zone_id)
        assert record is not None
        assert record["ResourceRecords"][0]["Value"] == "app-v2.internal.example.net"

        engine.destroy(auto_approve=True)
        assert _record(route53, zone_id) is None

    def test_dns_deploy_updates_existing_record(self, mocked_aws: None, dns_config: Path) -> None:
        route53 = boto3.client("route53", region_name="us-east-1")
        zone = route53.create_hosted_zone(Name="sokech.com", CallerReference="dns-flow-update")
        zone_id = zone["HostedZone"]["Id"].split("/")[-1]

        route53.change_resource_record_sets(
            HostedZoneId=zone_id,
            ChangeBatch={
                "Changes": [
                    {
                        "Action": "UPSERT",
                        "ResourceRecordSet": {
                            "Name": "example.sokech.com",
                            "Type": "CNAME",
                            "TTL": 300,
                            "ResourceRecords": [{"Value": "old-target.internal.example.net"}],
                        },
                    }
                ]
            },
        )

        cfg = load_config(dns_config)
        engine = Engine(cfg)
        engine.deploy(auto_approve=True)

        record = _record(route53, zone_id)
        assert record is not None
        assert record["ResourceRecords"][0]["Value"] == "app-v2.internal.example.net"

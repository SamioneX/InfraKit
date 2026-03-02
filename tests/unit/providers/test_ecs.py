"""Unit tests for the ECS Fargate provider."""

from __future__ import annotations

import boto3

from infrakit.providers.ecs import ECSFargateProvider
from infrakit.schema.models import ECSFargateResource


def _make_provider(
    mocked_aws: None,
    load_balancer: str | None = None,
) -> ECSFargateProvider:
    cfg = ECSFargateResource(
        type="ecs-fargate",  # type: ignore[arg-type]
        image="nginx:alpine",
        cpu=256,
        memory_mb=512,
        port=80,
        load_balancer=load_balancer,
        desired_count=1,
    )
    return ECSFargateProvider("web", cfg, project="myapp", env="dev")


class TestECSFargateProvider:
    def test_physical_name(self, mocked_aws: None) -> None:
        p = _make_provider(mocked_aws)
        assert p.physical_name == "myapp-dev-web"

    def test_cluster_name(self, mocked_aws: None) -> None:
        p = _make_provider(mocked_aws)
        assert p._cluster_name == "myapp-dev"

    def test_exists_false_when_no_service(self, mocked_aws: None) -> None:
        p = _make_provider(mocked_aws)
        assert p.exists() is False

    def test_create_service_no_lb(self, mocked_aws: None) -> None:
        p = _make_provider(mocked_aws)
        outputs = p.create()
        assert "name" in outputs
        assert "arn" in outputs
        assert "cluster" in outputs
        assert outputs["name"] == "myapp-dev-web"
        assert outputs["cluster"] == "myapp-dev"

    def test_exists_true_after_create(self, mocked_aws: None) -> None:
        p = _make_provider(mocked_aws)
        p.create()
        assert p.exists() is True

    def test_create_service_with_lb(self, mocked_aws: None) -> None:
        # Create a target group first to get a real ARN
        elbv2 = boto3.client("elbv2", region_name="us-east-1")
        ec2 = boto3.client("ec2", region_name="us-east-1")
        vpcs = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])
        vpc_id = vpcs["Vpcs"][0]["VpcId"]
        tg = elbv2.create_target_group(
            Name="test-tg",
            Protocol="HTTP",
            Port=80,
            VpcId=vpc_id,
            TargetType="ip",
        )
        tg_arn = tg["TargetGroups"][0]["TargetGroupArn"]

        p = _make_provider(mocked_aws, load_balancer=tg_arn)
        outputs = p.create()
        assert outputs["arn"].startswith("arn:aws:ecs")

    def test_delete_service(self, mocked_aws: None) -> None:
        p = _make_provider(mocked_aws)
        p.create()
        p.delete()
        assert p.exists() is False

    def test_delete_when_not_exists_is_safe(self, mocked_aws: None) -> None:
        p = _make_provider(mocked_aws)
        p.delete()  # should not raise

    def test_create_with_environment(self, mocked_aws: None) -> None:
        cfg = ECSFargateResource(
            type="ecs-fargate",  # type: ignore[arg-type]
            image="nginx:alpine",
            cpu=256,
            memory_mb=512,
            port=80,
            environment={"TABLE_NAME": "my-table", "ENV": "dev"},
        )
        p = ECSFargateProvider("svc", cfg, project="proj", env="dev")
        outputs = p.create()
        assert outputs["name"] == "proj-dev-svc"

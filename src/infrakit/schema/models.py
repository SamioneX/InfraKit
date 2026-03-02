"""Pydantic v2 models for the infrakit.yaml config schema.

These models are the contract between the user's YAML file and every
other part of InfraKit. Validation happens here — before any AWS call.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# State backend
# ---------------------------------------------------------------------------


class LocalStateConfig(BaseModel):
    backend: Literal["local"] = "local"
    path: str = ".infrakit/state.json"


class S3StateConfig(BaseModel):
    backend: Literal["s3"]
    bucket: str
    lock_table: str
    key_prefix: str = "infrakit"


StateConfig = Annotated[
    LocalStateConfig | S3StateConfig,
    Field(discriminator="backend"),
]


# ---------------------------------------------------------------------------
# Resource definitions
# ---------------------------------------------------------------------------


class DynamoDBResource(BaseModel):
    type: Literal["dynamodb"]
    billing: Literal["pay-per-request", "provisioned"] = "pay-per-request"
    hash_key: str
    hash_key_type: Literal["S", "N", "B"] = "S"
    sort_key: str | None = None
    sort_key_type: Literal["S", "N", "B"] | None = None
    read_capacity: int | None = None
    write_capacity: int | None = None
    ttl_attribute: str | None = None
    stream: bool = False

    @model_validator(mode="after")
    def _provisioned_requires_capacity(self) -> DynamoDBResource:
        if self.billing == "provisioned" and (
            self.read_capacity is None or self.write_capacity is None
        ):
            raise ValueError("billing=provisioned requires read_capacity and write_capacity")
        return self


class LambdaResource(BaseModel):
    type: Literal["lambda"]
    runtime: str = "python3.12"
    handler: str
    code: str = "."
    memory_mb: int = Field(default=128, ge=128, le=10240)
    timeout_s: int = Field(default=30, ge=1, le=900)
    environment: dict[str, str] = Field(default_factory=dict)
    role: str | None = None  # !ref or ARN
    layers: list[str] = Field(default_factory=list)
    schedule: str | None = None  # EventBridge schedule expression

    @field_validator("runtime")
    @classmethod
    def _valid_runtime(cls, v: str) -> str:
        valid = {
            "python3.11",
            "python3.12",
            "nodejs18.x",
            "nodejs20.x",
            "java17",
            "java21",
            "go1.x",
            "dotnet8",
        }
        if v not in valid:
            raise ValueError(f"runtime must be one of {sorted(valid)}, got {v!r}")
        return v


class IAMRoleResource(BaseModel):
    type: Literal["iam-role"]
    assumed_by: str  # e.g. "lambda.amazonaws.com"
    policies: list[str | dict[str, Any]] = Field(default_factory=list)


class APIGatewayResource(BaseModel):
    type: Literal["api-gateway"]
    integration: str  # !ref to a lambda resource
    routes: list[str] = Field(default_factory=list)
    stage: str = "prod"
    cors: bool = False


class S3Resource(BaseModel):
    type: Literal["s3"]
    versioning: bool = False
    public: bool = False
    lifecycle_days: int | None = None


class ECSFargateResource(BaseModel):
    type: Literal["ecs-fargate"]
    image: str
    command: list[str] = Field(default_factory=list)
    cpu: int = Field(default=256, description="vCPU units (256 = 0.25 vCPU)")
    memory_mb: int = Field(default=512)
    port: int = Field(default=8080, ge=1, le=65535)
    task_role: str | None = None
    load_balancer: str | None = None  # !ref alb.target_group_arn
    environment: dict[str, str] = Field(default_factory=dict)
    desired_count: int = Field(default=1, ge=0)


class ElastiCacheResource(BaseModel):
    type: Literal["elasticache"]
    engine: Literal["redis", "memcached"] = "redis"
    node_type: str = "cache.t3.micro"
    num_nodes: int = Field(default=1, ge=1)


class ALBResource(BaseModel):
    type: Literal["alb"]
    target: str | None = None  # optional annotation only — not used in AWS wiring
    port: int = Field(default=80, ge=1, le=65535)
    health_check_path: str = "/health"
    scheme: Literal["internet-facing", "internal"] = "internet-facing"


class DNSResource(BaseModel):
    type: Literal["dns"]
    provider: Literal["route53", "cloudflare"] = "route53"
    zone: str
    record: str = "@"
    target: str
    record_type: Literal["CNAME", "A", "AAAA", "TXT"] = "CNAME"
    ttl: int = Field(default=300, ge=60, le=86400)
    proxied: bool = False
    alias: bool = False
    target_hosted_zone_id: str | None = None
    evaluate_target_health: bool = False
    cloudflare_token_secret: str | None = None

    @model_validator(mode="after")
    def _validate_dns_settings(self) -> DNSResource:
        if self.alias:
            if self.provider != "route53":
                raise ValueError("alias is only supported with provider=route53")
            if self.record_type != "A":
                raise ValueError("alias=true requires record_type=A")
            if not self.target_hosted_zone_id:
                raise ValueError("alias=true requires target_hosted_zone_id")
        if self.provider == "route53" and self.proxied:
            raise ValueError("proxied is only supported with provider=cloudflare")
        if self.provider == "cloudflare" and self.target_hosted_zone_id:
            raise ValueError("target_hosted_zone_id is only supported with provider=route53")
        if self.zone.endswith("."):
            self.zone = self.zone[:-1]
        return self


# Discriminated union — Pydantic picks the right model from `type`
AnyResource = Annotated[
    DynamoDBResource
    | LambdaResource
    | IAMRoleResource
    | APIGatewayResource
    | S3Resource
    | ECSFargateResource
    | ElastiCacheResource
    | ALBResource
    | DNSResource,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Root config
# ---------------------------------------------------------------------------


class InfraKitConfig(BaseModel):
    """Root model — represents the entire infrakit.yaml file."""

    project: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    region: str = Field(default="us-east-1")
    env: Literal["dev", "staging", "prod"] = "dev"
    state: LocalStateConfig | S3StateConfig = Field(default_factory=LocalStateConfig)
    services: dict[str, AnyResource] = Field(default_factory=dict)

    @field_validator("services")
    @classmethod
    def _service_keys_are_valid(cls, v: dict[str, AnyResource]) -> dict[str, AnyResource]:
        for key in v:
            if not key.replace("_", "").replace("-", "").isalnum():
                raise ValueError(
                    f"Service name {key!r} must contain only letters, digits, "
                    "hyphens, and underscores."
                )
        return v

    @field_validator("region")
    @classmethod
    def _valid_region(cls, v: str) -> str:
        # Coarse check — real validation happens via AWS API.
        # Pattern: <area>-<direction>-<number> e.g. us-east-1
        import re

        if not re.match(r"^[a-z]+-[a-z]+-\d+$", v):
            raise ValueError(f"region {v!r} does not look like a valid AWS region")
        return v

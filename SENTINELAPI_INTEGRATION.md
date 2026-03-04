# SentinelAPI Integration Plan for InfraKit

## Decision

Integrate SentinelAPI as a first-class InfraKit resource type:

- `type: sentinelapi`
- No hard dependency on SentinelAPI/CDK in InfraKit core runtime.
- Provider implementation should call AWS APIs (CloudFormation + service clients), not shelling out to `cdk`.

This keeps InfraKit lightweight while still enabling SentinelAPI as a deployable abstraction.

## InfraKit-Native Config Contract

This contract follows InfraKit's existing config shape (`project/region/env/services`).

```yaml
project: my-platform
region: us-east-1
env: prod

services:
  sentinel:
    type: sentinelapi
    upstream_base_url: https://backend.example.com

    jwt:
      # at least one required
      secret_key: /myapp/sentinel-jwt-secret       # Secrets Manager secret name/ARN
      # public_key: /myapp/sentinel-jwt-public-key
      # jwks_url: https://idp.example.com/.well-known/jwks.json
      algorithm: HS256

    optimize_for: cost   # cost | performance

    fargate:
      cpu: 256
      memory_mib: 512
      desired_count: 1

    rate_limit:
      capacity: 100
      refill_rate: 1.0

    anomaly:
      threshold: 8.0
      min_requests: 40
      auto_block: true
      auto_block_ttl_seconds: 3600

    observability:
      log_retention_days: 7
      request_timeout_seconds: 10

  sentinel_dns:
    type: dns
    provider: cloudflare
    zone: sokech.com
    record: api-sentinel
    record_type: CNAME
    target: !ref sentinel.alb_dns_name
    cloudflare_token_secret: /sokech/cloudflare-token
```

## Schema Model Draft

Add the following Pydantic models in `src/infrakit/schema/models.py` and include in `AnyResource`:

- `SentinelJWTConfig`
  - `secret_key: str | None`
  - `public_key: str | None`
  - `jwks_url: str | None`
  - `algorithm: str = "HS256"`
  - validator: at least one of `secret_key/public_key/jwks_url`

- `SentinelFargateConfig`
  - `cpu: int | None`
  - `memory_mib: int | None`
  - `desired_count: int | None`

- `SentinelRateLimitConfig`
  - `capacity: int | None`
  - `refill_rate: float | None`

- `SentinelAnomalyConfig`
  - `threshold: float | None`
  - `min_requests: int | None`
  - `auto_block: bool | None`
  - `auto_block_ttl_seconds: int | None`

- `SentinelObservabilityConfig`
  - `log_retention_days: int | None`
  - `request_timeout_seconds: int | None`

- `SentinelAPIResource`
  - `type: Literal["sentinelapi"]`
  - `upstream_base_url: str`
  - `jwt: SentinelJWTConfig`
  - `optimize_for: Literal["cost", "performance"] = "cost"`
  - `fargate: SentinelFargateConfig = Field(default_factory=...)`
  - `rate_limit: SentinelRateLimitConfig = Field(default_factory=...)`
  - `anomaly: SentinelAnomalyConfig = Field(default_factory=...)`
  - `observability: SentinelObservabilityConfig = Field(default_factory=...)`

Validation rules:

1. `upstream_base_url` must be non-empty and URL-like.
2. At least one JWT source must be provided.
3. Numeric fields must respect sane ranges (`desired_count >= 1`, etc.).

## Provider Interface Draft

Create `src/infrakit/providers/sentinelapi.py` implementing `ResourceProvider`.

Required methods:

- `exists() -> bool`
  - Check CloudFormation stack by deterministic name.

- `create() -> dict[str, Any]`
  - Create/update stack with parameters from resource config.
  - Wait for completion.
  - Return stable outputs (below).

- `delete() -> None`
  - Delete stack and wait for completion.
  - Idempotent on not-found.

### Stack naming

`<project>-<env>-<logical-name>-sentinel` (normalized to CFN limits).

### Required outputs contract

Provider must return these output keys for `!ref` use:

- `alb_dns_name`
- `service_url`
- `ecs_cluster_name`
- `ecs_service_name`
- `request_logs_table_name`
- `traffic_aggregate_table_name`
- `blocklist_table_name`
- `anomaly_detector_function_name`
- `optimize_for_resolved`

Also include compatibility aliases so users can reference your original camelCase names if needed:

- `albDnsName`, `serviceUrl`, etc.

## Implementation Phases

## Phase 1 (MVP)

Goal: deliver deployable SentinelAPI abstraction quickly.

- Add schema/resource type + provider wiring in engine.
- Provider deploys a CloudFormation stack from a packaged template artifact.
- Support core knobs:
  - `upstream_base_url`, `jwt`, `optimize_for`
  - optional `fargate.desired_count`
- Return full outputs contract.
- Add example:
  - `examples/sentinelapi/infrakit.yaml`
  - optional DNS CNAME using `!ref sentinel.alb_dns_name`
- Add tests:
  - schema validation tests
  - provider unit tests with mocked CFN outputs
  - integration test for deploy/destroy lifecycle (moto where possible; otherwise mocked CFN client)

## Phase 2 (Production-ready)

Goal: match SentinelAPI v0.6.0 capability and operational safety.

- Full knob coverage (rate_limit, anomaly, observability, all fargate overrides).
- In-place update behavior via `update()` (CFN update stack) instead of delete/recreate.
- Drift-friendly outputs and robust not-found handling.
- Backward-compatible alias outputs (snake_case + camelCase).
- Expanded tests:
  - update path
  - parameter diff idempotency
  - failure rollback/cleanup edge cases
- Docs:
  - root README resource docs
  - config reference for `sentinelapi`
  - production example with DNS mapping

## Dependency Strategy

Do **not** add SentinelAPI as a required dependency of InfraKit core.

Use one of these instead:

1. InfraKit-owned CloudFormation template artifact for SentinelAPI (recommended first).
2. Optional extra package/plugin (`infrakit[sentinelapi]`) if shared code is needed later.

This avoids forcing CDK toolchain and Sentinel internals onto all InfraKit users.

## Acceptance Criteria

- `infrakit validate` accepts valid `sentinelapi` configs and rejects invalid JWT/upstream fields.
- `infrakit deploy` provisions SentinelAPI and exposes expected outputs for `!ref`.
- `infrakit destroy` removes SentinelAPI resources cleanly.
- DNS integration works through existing `dns` resource against `!ref sentinel.alb_dns_name`.
- Coverage remains >= 90%.

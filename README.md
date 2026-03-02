# InfraKit

> Declarative AWS infrastructure from a single YAML file.

```bash
pip install sokech-infrakit && infrakit deploy
```

[![CI](https://github.com/SamioneX/InfraKit/actions/workflows/ci.yml/badge.svg)](https://github.com/SamioneX/InfraKit/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/sokech-infrakit)](https://pypi.org/project/sokech-infrakit/)
[![Coverage](https://img.shields.io/badge/coverage-90%25-brightgreen)](https://github.com/SamioneX/InfraKit)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://pypi.org/project/sokech-infrakit/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What is InfraKit?

InfraKit is a production-grade CLI tool that reads an `infrakit.yaml` file and provisions AWS infrastructure with the properties that matter in real deployments: idempotency, atomic rollback, drift detection, and remote state with distributed locking.

Define your stack in YAML. Deploy, detect drift, and recover — all from the CLI.

```yaml
# infrakit.yaml
project: my-api
region:  us-east-1
env:     prod

services:
  users_table:
    type: dynamodb
    billing: pay-per-request
    hash_key: userId
    hash_key_type: S

  api_role:
    type: iam-role
    assumed_by: lambda.amazonaws.com
    policies:
      - arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

  api_handler:
    type: lambda
    runtime: python3.12
    handler: app.handler
    code: ./src
    role: !ref api_role.arn
    environment:
      TABLE_NAME: !ref users_table.name

  api_gateway:
    type: api-gateway
    integration: !ref api_handler.arn
    routes:
      - GET  /users/{id}
      - POST /users
```

```bash
$ infrakit plan

  + users_table    (dynamodb)     will be created
  + api_role       (iam-role)     will be created
  + api_handler    (lambda)       will be created
  + api_gateway    (api-gateway)  will be created

  Plan: 4 to create, 0 to update, 0 to destroy.

$ infrakit deploy --auto-approve
  + users_table    (dynamodb)    — creating  ✓
  + api_role       (iam-role)    — creating  ✓
  + api_handler    (lambda)      — creating  ✓
  + api_gateway    (api-gateway) — creating  ✓

  Deploy complete.

# Later — someone deletes users_table from the AWS console
$ infrakit drift

  ┌──────────────┬──────────┬─────────┬──────────────────────────────┐
  │ Name         │ Type     │ Status  │ Detail                       │
  ├──────────────┼──────────┼─────────┼──────────────────────────────┤
  │ users_table  │ dynamodb │ MISSING │ Resource deleted out-of-band. │
  │ api_role     │ iam-role │ OK      │                              │
  │ api_handler  │ lambda   │ OK      │                              │
  │ api_gateway  │ api-gtw  │ OK      │                              │
  └──────────────┴──────────┴─────────┴──────────────────────────────┘

  Drift detected: 1 missing, 0 error(s).
  Run `infrakit deploy` to reconcile.

$ infrakit deploy --auto-approve
  = api_role       (iam-role)    — no changes
  ! users_table    (dynamodb)    — drift detected, recreating  ✓
  = api_handler    (lambda)      — no changes
  = api_gateway    (api-gateway) — no changes

  Deploy complete.
```

---

## Roadmap

| Phase | Goal | Status |
|-------|------|--------|
| **Phase 1** | Core — schema validation, 5 resource providers, deploy/destroy/plan CLI | ✅ **Complete** |
| **Phase 2** | DX — `infrakit init`, PyPI publish, Docker image, idempotency improvements | ✅ **Complete** |
| **Phase 3** | DevOps — S3+DynamoDB remote state, ECS/ElastiCache/ALB providers, GitHub Action | ✅ **Complete** |
| **Phase 4** | Reliability — drift detection, atomic rollback observability, machine-readable plan output | ✅ **Complete** |

### Phase 4 deliverables (complete)

- **`infrakit drift`** — compares state file against live AWS; reports each resource as `OK`, `MISSING`, or `ERROR`; exits 1 when drift is detected so CI pipelines can alert
- **`infrakit plan --json`** — machine-readable plan output for CI systems; returns `creates`, `deletes`, `has_changes` as structured JSON
- **`Engine.plan_data()`** — single source of truth for plan logic; shared by human-readable table output and `--json` flag
- **Rollback observability** — writes `status="failed"` to state before attempting delete so a crash mid-rollback leaves a traceable record; reports any resources that could not be cleaned up
- 184 tests, 90.2% coverage, mypy strict + ruff passing
- **Live AWS verified** — deploy task-manager stack → delete DynamoDB table out-of-band → `infrakit drift` reports MISSING, exit 1 → `infrakit deploy` recovers → `infrakit drift` reports all OK, exit 0

### Phase 3 deliverables (complete)

- **S3 + DynamoDB remote state backend** — same pattern as Terraform; safe for concurrent CI runners
- **ECS Fargate provider** — auto-detects default VPC/subnets; registers with ALB target group via `load_balancer: !ref alb.target_group_arn`
- **ElastiCache provider** — Redis and Memcached clusters; VPC-aware subnet group and security group management
- **ALB provider** — Application Load Balancer + target group + listener; outputs `target_group_arn` for ECS wiring
- **GitHub Action** (`action.yml`) — composite action for `infrakit plan/deploy/destroy` in any workflow
- **`examples/task-manager/`** — deployable ECS Fargate + ALB + DynamoDB example; used in Phase 4 drift detection demo
- 166 tests, 90.6% coverage, mypy strict + ruff passing

### Phase 2 deliverables (complete)

- `infrakit init` — interactive scaffolding command; generates a starter `infrakit.yaml` for `serverless-api` or `data-store` project types
- Published to **PyPI** as [`sokech-infrakit`](https://pypi.org/project/sokech-infrakit/) — `pip install sokech-infrakit` works
- **Multi-arch Docker image** (`linux/amd64` + `linux/arm64`) published to GHCR on every tag
- **Deploy idempotency** — running `infrakit deploy` twice on an unchanged stack prints "All resources up to date." and exits 0; drift (resource deleted in AWS) triggers a targeted recreate
- GitHub Actions CI on every push (Python 3.11 + 3.12), PyPI publish and Docker push on tag
- 129 tests, 91.8% coverage, mypy strict + ruff passing

### Phase 1 deliverables (complete)

- Pydantic v2 schema validation — all errors reported before any AWS call
- Resource providers: `dynamodb`, `lambda`, `api-gateway`, `s3`, `iam-role`
- `!ref` syntax for cross-resource references (resolved via dependency DAG)
- Dependency graph (DAG) — resources provisioned in correct order automatically
- Local JSON state backend with advisory locking
- Atomic rollback on deploy failure
- `infrakit validate`, `infrakit plan`, `infrakit deploy`, `infrakit destroy`, `infrakit status`
- 115 tests, 91% coverage enforced in CI

---

## Installation

**Local / development**
```bash
git clone https://github.com/SamioneX/InfraKit
cd InfraKit
pip install -e ".[dev]"
```

**pip**
```bash
pip install sokech-infrakit
```

**Docker**
```bash
docker run --rm \
  -v ~/.aws:/root/.aws:ro \
  -v $(pwd):/workspace \
  -w /workspace \
  ghcr.io/samionex/infrakit deploy
```

---

## Commands

| Command | Description |
|---------|-------------|
| `infrakit validate` | Validate config schema without calling AWS |
| `infrakit plan` | Show what would change without applying (`--json` for CI output) |
| `infrakit deploy` | Provision all resources in dependency order; recovers drifted resources |
| `infrakit destroy` | Tear down all managed resources in reverse dependency order |
| `infrakit status` | Show current state from the state file |
| `infrakit init` | Scaffold a new `infrakit.yaml` interactively |
| `infrakit drift` | Compare state against live AWS; exits 1 if drift is detected |

---

## Supported Resource Types

| Type | AWS Resource |
|------|-------------|
| `dynamodb` | Amazon DynamoDB Table |
| `iam-role` | AWS IAM Role + inline and managed policies |
| `lambda` | AWS Lambda Function |
| `api-gateway` | Amazon API Gateway (HTTP API v2) |
| `s3` | Amazon S3 Bucket |
| `ecs-fargate` | ECS Fargate Service + Task Definition |
| `elasticache` | ElastiCache Cluster (Redis / Memcached) |
| `alb` | Application Load Balancer + target group + listener |
| `dns` | DNS record via Route53 or Cloudflare |

---

## Config Reference

### Top-level fields

```yaml
project: my-api       # used for resource naming and state key
region:  us-east-1    # AWS region
env:     prod         # dev | staging | prod
```

### State backend

```yaml
state:
  backend: local                   # local (default) | s3
  path: .infrakit/state.json       # local backend path

# Remote backend (S3 + DynamoDB locking — same pattern as Terraform)
state:
  backend: s3
  bucket: my-infrakit-state        # must pre-exist
  lock_table: infrakit-locks       # DynamoDB table (LockID String primary key); must pre-exist
```

### `!ref` syntax

Reference an output attribute of another resource — InfraKit resolves the
correct provisioning order automatically:

```yaml
role: !ref api_role.arn
environment:
  TABLE_NAME: !ref users_table.name
```

Supported attributes per resource type:

| Type | Attributes |
|------|-----------|
| `dynamodb` | `.name`, `.arn`, `.stream_arn` |
| `lambda` | `.name`, `.arn`, `.function_name` |
| `iam-role` | `.arn`, `.name` |
| `s3` | `.name`, `.arn`, `.bucket_url` |
| `api-gateway` | `.endpoint`, `.id` |
| `ecs-fargate` | `.name`, `.arn`, `.cluster` |
| `elasticache` | `.name`, `.endpoint`, `.port`, `.arn` |
| `alb` | `.id`, `.endpoint`, `.arn`, `.hosted_zone_id`, `.target_group_arn` |
| `dns` | `.provider`, `.zone`, `.record`, `.record_type`, `.target` |

### DNS records (`dns`)

```yaml
# Route53 CNAME (minimal)
api_dns:
  type: dns
  provider: route53
  zone: sokech.com
  record: api
  target: !ref app_alb.endpoint

# Cloudflare CNAME using token in AWS Secrets Manager
api_dns_cf:
  type: dns
  provider: cloudflare
  zone: sokech.com
  record: api
  target: !ref app_alb.endpoint
  proxied: true
  # optional override (default: /<project>/cloudflare-token)
  cloudflare_token_secret: /sokech/cloudflare-token

# Route53 alias A record (useful for apex)
root_dns:
  type: dns
  provider: route53
  zone: sokech.com
  record: "@"
  record_type: A
  alias: true
  target: !ref app_alb.endpoint
  target_hosted_zone_id: !ref app_alb.hosted_zone_id
```

---

## State Management

InfraKit tracks deployed resources in a state file. Resources are saved
individually — a failed deploy only rolls back what was created in that run.

```bash
$ cat .infrakit/state.json
{
  "resources": {
    "users_table": {
      "type": "dynamodb",
      "outputs": { "name": "my-api-prod-users_table", "arn": "arn:aws:..." },
      "status": "created"
    }
  }
}
```

For team and CI/CD use, switch to the remote S3+DynamoDB backend (same pattern as Terraform) —
see the [State backend](#state-backend) config section above.

---

## Development

```bash
git clone https://github.com/SamioneX/InfraKit
cd InfraKit
pip install -e ".[dev]"

make test      # pytest + coverage report (must be ≥90%)
make lint      # ruff check + mypy
make format    # ruff format
```

### Test structure

```
tests/
├── unit/           # pure Python, no AWS calls
│   ├── providers/  # one file per provider
│   ├── test_schema.py
│   ├── test_dependency.py
│   ├── test_state.py
│   └── test_cli.py
└── integration/    # full deploy/destroy flows via moto
    └── test_deploy_flow.py
```

All AWS calls are mocked with [moto](https://github.com/getmoto/moto) — no AWS account or credentials required to run the test suite.

---

## Architecture Decisions

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed rationale behind key design choices:

- **Typer** over Click — type annotations as CLI argument definitions, Rich output built in
- **Pydantic v2** for schema validation — schema-as-code, human-readable errors, validated before any AWS call
- **AWS session Singleton** — single injection point for mocking, minimal connection overhead
- **Dependency DAG** (networkx) — automatic resource ordering, cycle detection at validation time
- **S3 + DynamoDB state** — same pattern as Terraform, safe for concurrent CI runners

---

## License

MIT © [Samuel Okechukwu](https://github.com/SamioneX)

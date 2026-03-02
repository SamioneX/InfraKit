# InfraKit

> Declarative AWS infrastructure from a single YAML file.

```bash
pip install sokech-infrakit && infrakit deploy
```

[![CI](https://github.com/SamioneX/InfraKit/actions/workflows/ci.yml/badge.svg)](https://github.com/SamioneX/InfraKit/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/sokech-infrakit)](https://pypi.org/project/sokech-infrakit/)
[![Coverage](https://img.shields.io/badge/coverage-91%25-brightgreen)](https://github.com/SamioneX/InfraKit)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://pypi.org/project/sokech-infrakit/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What is InfraKit?

InfraKit is a CLI tool that reads an `infrakit.yaml` file and provisions the described AWS infrastructure. Think of it as a lightweight, opinionated alternative to the AWS CDK — without the boilerplate.

Define your stack, run one command, done.

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
  + users_table    created
  + api_role       created
  + api_handler    created
  + api_gateway    created

  Deploy complete.
```

---

## Roadmap

| Phase | Goal | Status |
|-------|------|--------|
| **Phase 1** | Core — schema validation, 5 resource providers, deploy/destroy/plan CLI | ✅ **Complete** |
| **Phase 2** | DX — `infrakit init`, PyPI publish, Docker image, idempotency improvements | ⬜ Next |
| **Phase 3** | DevOps — S3+DynamoDB remote state, GitHub Action | ⬜ Planned |
| **Phase 4** | Reliability — atomic rollback, drift detection, cost estimation | ⬜ Planned |

### Phase 1 deliverables (complete)

- Pydantic v2 schema validation — all errors reported before any AWS call
- Resource providers: `dynamodb`, `lambda`, `api-gateway`, `s3`, `iam-role`
- `!ref` syntax for cross-resource references (resolved via dependency DAG)
- Dependency graph (DAG) — resources provisioned in correct order automatically
- Local JSON state backend with advisory locking
- Atomic rollback on deploy failure
- `infrakit validate`, `infrakit plan`, `infrakit deploy`, `infrakit destroy`, `infrakit status`
- 112 tests, 91% coverage enforced in CI

---

## Installation

**Local / development**
```bash
git clone https://github.com/SamioneX/InfraKit
cd InfraKit
pip install -e ".[dev]"
```

**pip (once published to PyPI — Phase 2)**
```bash
pip install sokech-infrakit
```

**Docker (Phase 2)**
```bash
docker run --rm \
  -v ~/.aws:/root/.aws:ro \
  -v $(pwd):/workspace \
  -w /workspace \
  ghcr.io/samionex/infrakit deploy
```

---

## Commands

| Command | Description | Status |
|---------|-------------|--------|
| `infrakit validate` | Validate config schema without calling AWS | ✅ |
| `infrakit plan` | Show what would change without applying | ✅ |
| `infrakit deploy` | Provision all resources in dependency order | ✅ |
| `infrakit destroy` | Tear down all managed resources | ✅ |
| `infrakit status` | Show current state from local state file | ✅ |
| `infrakit init` | Scaffold a new `infrakit.yaml` interactively | ⬜ Phase 2 |
| `infrakit drift` | Detect out-of-band changes in AWS | ⬜ Phase 4 |

---

## Supported Resource Types

| Type | AWS Resource | Phase |
|------|-------------|-------|
| `dynamodb` | Amazon DynamoDB Table | ✅ Phase 1 |
| `iam-role` | AWS IAM Role + policies | ✅ Phase 1 |
| `lambda` | AWS Lambda Function | ✅ Phase 1 |
| `api-gateway` | Amazon API Gateway (HTTP API v2) | ✅ Phase 1 |
| `s3` | Amazon S3 Bucket | ✅ Phase 1 |
| `ecs-fargate` | ECS Fargate Service + Task Definition | ⬜ Phase 3 |
| `elasticache` | ElastiCache Cluster (Redis) | ⬜ Phase 3 |
| `alb` | Application Load Balancer | ⬜ Phase 3 |

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
  backend: local                   # local (default) | s3 (Phase 3)
  path: .infrakit/state.json       # local backend path

# Phase 3: remote backend
state:
  backend: s3
  bucket: my-infrakit-state
  lock_table: infrakit-locks       # DynamoDB table for distributed locking
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

For team and CI/CD use, a remote S3+DynamoDB backend (same pattern as Terraform)
is coming in Phase 3.

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
- **S3 + DynamoDB state** (Phase 3) — same pattern as Terraform, safe for concurrent CI runners

---

## License

MIT © [Samuel Okechukwu](https://github.com/SamioneX)

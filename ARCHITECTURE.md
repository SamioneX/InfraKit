# InfraKit Architecture Decisions

This document explains the key design decisions made in InfraKit, including the rationale and trade-offs considered. These are the answers to "why did you build it this way?" — the question every technical interview comes down to.

---

## CLI Framework: Typer

**Decision:** Use [Typer](https://typer.tiangolo.com/) instead of Click or argparse.

**Rationale:** Typer wraps Click and adds Python type annotation support for automatic argument parsing and help text generation. This means CLI commands read like regular Python functions — no decorator-as-documentation anti-pattern. Rich integration is built in, giving us color output, progress bars, and tables without extra work.

**Trade-off:** Typer is a thinner ecosystem than Click. For simple CLIs this is fine; for deeply complex CLIs with plugins, Click's ecosystem is broader.

**In an interview:** *"I chose Typer because it lets me define CLI arguments using Python type annotations, which keeps the code self-documenting and eliminates the boilerplate of manually writing help strings and type coercions."*

---

## Schema Validation: Pydantic v2

**Decision:** Validate the YAML config using [Pydantic v2](https://docs.pydantic.dev/) models before any AWS call.

**Rationale:** Pydantic v2 (rewritten in Rust) is the fastest validation library in the Python ecosystem. Schema is defined as Python dataclasses — it's readable, IDE-friendly, and produces detailed error messages automatically. Crucially, all validation happens before the first AWS API call, so users get immediate feedback on config errors rather than discovering problems mid-deployment.

**Alternative considered:** `jsonschema` was rejected because it separates schema from code (a separate JSON file), making it harder to maintain. `marshmallow` was rejected because it's slower and has a less ergonomic API.

**In an interview:** *"I chose Pydantic v2 because it validates the entire config upfront with clear, field-level error messages — before a single AWS API call is made. This is a better DX than failing mid-deployment because the user forgot a required field."*

---

## AWS Session: Singleton Pattern

**Decision:** A single `AWSSession` class is instantiated once and shared across all resource providers.

**Rationale:** Creating a new AWS session and client per resource wastes connection overhead and credential resolution time. More importantly, the Singleton provides a single point for injecting mocked clients in tests — instead of mocking `boto3.client` globally, tests inject a mock `AWSSession` at construction time.

```python
# All providers receive the session at construction, not at call time
provider = LambdaProvider(session=AWSSession.get_instance())
```

**In an interview:** *"I used a Singleton for the AWS session provider for two reasons: to avoid redundant credential resolution on every resource operation, and to make the session injectable — which is what makes the entire codebase testable without real AWS credentials."*

---

## Resource Ordering: Directed Acyclic Graph (DAG)

**Decision:** Build a dependency graph from `!ref` expressions in the config and resolve creation order automatically.

**Rationale:** Resources have implicit dependencies — a Lambda needs its IAM role to exist first; an API Gateway needs a Lambda. Requiring users to manually order resources in YAML is error-prone. Instead, InfraKit parses `!ref` expressions to discover dependencies, builds a DAG using NetworkX, and performs a topological sort to determine the correct creation order. Circular dependencies are caught at validation time with a clear error.

**In an interview:** *"Rather than requiring users to manually order resources, I parse the `!ref` references in the config to build a dependency graph, then topologically sort it. This means InfraKit always provisions resources in the right order — and catches circular dependencies before touching AWS."*

---

## State Backend: S3 + DynamoDB Locking

**Decision:** Remote state stored as JSON in S3, with DynamoDB as a distributed lock.

**Rationale:** This is the same pattern Terraform uses — and for the same reasons. S3 provides durable, versioned storage for the state file. DynamoDB provides atomic conditional writes (via `ConditionExpression`), which means only one `infrakit apply` can hold the lock at a time. The state file is plain JSON — human-readable and inspectable without special tooling.

Local state (a `.infrakit/state.json` file) is supported for solo development, but remote state is the default for anything beyond a single developer.

**In an interview:** *"I implemented the same S3+DynamoDB state locking pattern that Terraform uses — not because it's the only option, but because it's the right one. S3 is durable and versioned; DynamoDB's conditional writes give you atomic locking without a separate lock server."*

---

## Testing: pytest + moto (no live AWS)

**Decision:** All tests run without real AWS credentials using [moto](https://docs.getmoto.org/).

**Rationale:** Tests that hit real AWS are slow (seconds per test vs. milliseconds), cost money, and are non-deterministic (network failures, eventual consistency). `moto` intercepts `boto3` calls and emulates AWS services in-process. The full test suite runs in seconds, completely offline, with no AWS account needed.

90% coverage is enforced in CI — the build fails below this threshold. In DevOps, untested deployment code is a liability, not just a best practice.

**In an interview:** *"The test suite uses moto to mock all AWS API calls, so tests run in milliseconds with no AWS account or real credentials. Coverage is enforced at 90% in CI — if a PR drops it below that, it doesn't merge."*

---

## Rollback: Atomic Failure Handling

**Decision:** If any resource fails to provision during `infrakit apply`, all resources created in that run are torn down.

**Rationale:** Partial deployments leave infrastructure in an unknown state that's often worse than no deployment at all. InfraKit tracks which resources it creates in the current run (not in the stored state, which represents the last known good state). On failure, it attempts to destroy every resource it created in that run, then reports the failure. The stored state is only updated for resources that are confirmed stable.

**In an interview:** *"On failure, InfraKit rolls back everything it provisioned in the current run — not just the failed resource. This means you either get the whole stack or nothing. Partial deployments are harder to reason about than a clean failure."*

---

## Distribution: pyproject.toml + Trusted PyPI Publishing

**Decision:** Package with `pyproject.toml` (not `setup.py`); publish to PyPI using OIDC trusted publishing (no API key stored in GitHub Secrets).

**Rationale:** `setup.py` is legacy Python packaging. `pyproject.toml` (PEP 517/518) is the modern standard, supported by all current tools. OIDC trusted publishing means the PyPI API token is never stored as a GitHub Secret — the GitHub Actions runner authenticates directly to PyPI using a short-lived OIDC token. This is the most secure way to automate PyPI releases as of 2024.

**In an interview:** *"Publishing uses OIDC trusted publishing so there's no long-lived API token stored in GitHub Secrets. The Actions runner gets a short-lived token scoped to a specific workflow run — if the token leaks, it's already expired."*

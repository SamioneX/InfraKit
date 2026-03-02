# Example: example.sokech.com

Deploys a minimal public HTTP service and maps `example.sokech.com` in Cloudflare.

## What this deploys

| Resource | Type | Purpose |
|----------|------|---------|
| `example_alb` | `alb` | Internet-facing ALB on port 80 |
| `example_service` | `ecs-fargate` | `hashicorp/http-echo` container returning a fixed message |
| `example_dns` | `dns` | Cloudflare CNAME `example.sokech.com` -> ALB endpoint |

The service responds with:

```text
Hello! You successfully reached example.sokech.com
```

## Prerequisites

- InfraKit installed
- AWS credentials configured
- Cloudflare API token stored in AWS Secrets Manager at `/sokech/cloudflare-token`
- Cloudflare token must have DNS edit permissions for zone `sokech.com`

## Deploy

```bash
cd examples/example
infrakit validate --config infrakit.yaml
infrakit plan --config infrakit.yaml
infrakit deploy --config infrakit.yaml --auto-approve
```

## Verify

Wait until ECS task is healthy behind the ALB (usually 1-2 minutes), then:

```bash
curl -s http://example.sokech.com
```

Expected:

```text
Hello! You successfully reached example.sokech.com
```

## Update if domain is already in use

InfraKit uses DNS UPSERT behavior, so redeploying updates the existing `example.sokech.com` record to the current ALB endpoint.

## Destroy

```bash
infrakit destroy --config infrakit.yaml --auto-approve
```

Destroy removes ECS/ALB resources and the Cloudflare DNS record managed by `example_dns`.

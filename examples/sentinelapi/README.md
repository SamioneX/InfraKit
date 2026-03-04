# Example: sentinelapi

Deploy SentinelAPI as an InfraKit resource, then map DNS to the ALB output.

## Resources

- `sentinel` (`sentinelapi`) - deploys Sentinel full stack via `sentinel-api` SDK
- `sentinel_dns` (`dns`) - optional CNAME to `!ref sentinel.alb_dns_name`

## Prerequisites

- InfraKit installed from this repo (`pip install -e ".[dev]"`)
- AWS credentials configured
- `sentinel-api` dependency installed (included in InfraKit dependencies)
- JWT secret present in AWS Secrets Manager at `/myapp/sentinel-jwt-secret` (or update config)

## Deploy

```bash
cd examples/sentinelapi
infrakit validate --config infrakit.yaml
infrakit plan --config infrakit.yaml
infrakit deploy --config infrakit.yaml --auto-approve
```

## Destroy

```bash
infrakit destroy --config infrakit.yaml --auto-approve
```

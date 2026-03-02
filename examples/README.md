# InfraKit Examples

Each subdirectory is a self-contained example with its own `infrakit.yaml` and a `README.md` explaining how to run it.

| Example | Resources | Description |
|---------|-----------|-------------|
| [hello-api](hello-api/) | IAM role + Lambda + API Gateway | Minimal serverless HTTP API |
| [example](example/) | ALB + ECS Fargate + DNS (Cloudflare) | Public hello service at `example.sokech.com` |

## General usage pattern

```bash
cd examples/<example-name>

infrakit validate --config infrakit.yaml   # validate config, no AWS calls
infrakit plan    --config infrakit.yaml   # preview changes
infrakit deploy  --config infrakit.yaml --auto-approve   # provision
infrakit status  --config infrakit.yaml   # inspect state
infrakit destroy --config infrakit.yaml --auto-approve   # tear down
```

> All commands must be run from within the example directory so that relative `code:` paths in the config resolve correctly.

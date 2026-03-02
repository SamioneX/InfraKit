# Example: hello-api

A minimal serverless API deployed with a single `infrakit deploy` command.

## What this deploys

| Resource | Type | Description |
|----------|------|-------------|
| `lambda_role` | `iam-role` | IAM execution role for the Lambda function |
| `hello_fn` | `lambda` | Python 3.12 function that returns a JSON greeting |
| `hello_api` | `api-gateway` | HTTP API Gateway with a `GET /hello` route |

InfraKit resolves the dependencies automatically — the role is created first, then the function, then the gateway.

## Prerequisites

- Python 3.11+, `infrakit` installed (`pip install -e ".[dev]"` from the repo root)
- AWS credentials configured (e.g. `aws configure` or environment variables)
- IAM permissions to create Lambda functions, IAM roles, and API Gateway APIs

## Run it

All commands must be run from this directory (`examples/hello-api/`), because `code: ./src` in the config is resolved relative to the working directory.

```bash
cd examples/hello-api
```

**1. Validate the config (no AWS calls)**
```bash
infrakit validate --config infrakit.yaml
```

**2. Preview what will be created**
```bash
infrakit plan --config infrakit.yaml
```

Expected output:
```
  +  lambda_role  (iam-role)      will be created
  +  hello_fn     (lambda)        will be created
  +  hello_api    (api-gateway)   will be created

  Plan: 3 to create, 0 to update, 0 to destroy.
```

**3. Deploy**
```bash
infrakit deploy --config infrakit.yaml --auto-approve
```

> Note: Lambda creation retries for up to ~25 seconds while the new IAM role propagates globally. This is normal AWS behaviour.

**4. Check state**
```bash
infrakit status --config infrakit.yaml
```

Copy the `endpoint` value from the `hello_api` row — it looks like:
```
https://<id>.execute-api.us-east-1.amazonaws.com/dev
```

**5. Call the API**
```bash
curl https://<id>.execute-api.us-east-1.amazonaws.com/dev/hello
```

Expected response:
```json
{
  "message": "Hello from InfraKit!",
  "method": "GET",
  "path": "/dev/hello"
}
```

**6. Destroy (clean up all resources)**
```bash
infrakit destroy --config infrakit.yaml --auto-approve
```

Resources are destroyed in reverse dependency order: API Gateway → Lambda → IAM role.

## Cost

This example stays within the [AWS Free Tier](https://aws.amazon.com/free/):
- Lambda: first 1M requests/month free
- API Gateway HTTP API: first 1M requests/month free
- IAM: always free

Destroy the stack when you're done to avoid any charges.

## Files

```
hello-api/
├── infrakit.yaml   # InfraKit config — defines the 3 resources
└── src/
    └── handler.py  # Lambda handler code
```

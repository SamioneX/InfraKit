# task-manager example

A minimal task management service deployed on ECS Fargate, fronted by an Application
Load Balancer, with DynamoDB for storage.

## Stack

| Resource | Type | Notes |
|----------|------|-------|
| `task_table` | DynamoDB | Tasks with TTL |
| `task_role` | IAM Role | ECS task execution role |
| `task_alb` | ALB | Internet-facing HTTP load balancer |
| `task_service` | ECS Fargate | `nginx:alpine` (swap for your own image) |

## Deploy

```bash
# Prerequisites: AWS CLI configured, default VPC present in us-east-1
cd examples/task-manager

infrakit plan                          # preview changes
infrakit deploy --auto-approve         # provision all resources
infrakit status                        # inspect state
```

After deploy, the ALB endpoint is shown in `infrakit status` under `task_alb → endpoint`.

## Destroy

```bash
infrakit destroy --auto-approve
```

## Remote state (optional)

To use S3 + DynamoDB state for team or CI use, add to `infrakit.yaml`:

```yaml
state:
  backend: s3
  bucket: my-infrakit-state        # must pre-exist
  lock_table: infrakit-locks       # DynamoDB table, LockID (String) primary key
```

## Phase 4 — Drift Detection

Once deployed, delete the `task_table` DynamoDB table from the AWS console, then run:

```bash
infrakit drift   # will detect the deleted table and report it
```

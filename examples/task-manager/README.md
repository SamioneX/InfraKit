# task-manager example

A minimal task management service deployed on ECS Fargate, fronted by an Application Load Balancer, with DynamoDB for storage. Use this example to walk through the full InfraKit lifecycle: plan → deploy → update → destroy.

## Stack

| Resource | Type | Purpose |
|----------|------|---------|
| `task_table` | DynamoDB | Task records with TTL auto-expiry |
| `task_role` | IAM Role | ECS task execution role |
| `task_alb` | ALB | Internet-facing HTTP load balancer |
| `task_service` | ECS Fargate | `nginx:alpine` container (swap for your image) |

Dependency order is resolved automatically. InfraKit deploys `task_table`, `task_role`, and `task_alb` in parallel-compatible order, then `task_service` last (it references outputs from the other three).

## Prerequisites

- AWS CLI configured with credentials (`aws configure` or environment variables)
- Default VPC present in `us-east-1` (true for most accounts; run `aws ec2 describe-vpcs --filters Name=isDefault,Values=true` to verify)
- InfraKit installed: `pip install sokech-infrakit`

## 1. Preview changes (plan)

Before touching AWS, see exactly what will be created:

```
$ cd examples/task-manager
$ infrakit plan

  Plan
  ┌──────────────┬─────────────┬────────┐
  │ Resource     │ Type        │ Action │
  ├──────────────┼─────────────┼────────┤
  │ task_table   │ dynamodb    │ create │
  │ task_role    │ iam-role    │ create │
  │ task_alb     │ alb         │ create │
  │ task_service │ ecs-fargate │ create │
  └──────────────┴─────────────┴────────┘

  Plan: 4 to create, 0 to delete.
```

No AWS mutating calls are made — `plan` only reads state and config.

## 2. Deploy

```
$ infrakit deploy --auto-approve

  + task_table (dynamodb) — creating
  + task_role (iam-role) — creating
  + task_alb (alb) — creating
  + task_service (ecs-fargate) — creating

  Deploy complete.
```

> **Note:** The ECS service may take 60–90 seconds if the IAM execution role needs time to propagate. InfraKit retries automatically with backoff — no action required.

## 3. Inspect deployed resources

```
$ infrakit status

  InfraKit State
  ┌──────────────┬─────────────┬─────────┬──────────────────────────────────────────────────────┐
  │ Name         │ Type        │ Status  │ Outputs                                              │
  ├──────────────┼─────────────┼─────────┼──────────────────────────────────────────────────────┤
  │ task_table   │ dynamodb    │ created │ name: task-manager-dev-task-table                    │
  │              │             │         │ arn: arn:aws:dynamodb:us-east-1:...                  │
  ├──────────────┼─────────────┼─────────┼──────────────────────────────────────────────────────┤
  │ task_role    │ iam-role    │ created │ arn: arn:aws:iam::...:role/task-manager-dev-task-role │
  │              │             │         │ name: task-manager-dev-task-role                     │
  ├──────────────┼─────────────┼─────────┼──────────────────────────────────────────────────────┤
  │ task_alb     │ alb         │ created │ endpoint: task-manager-dev-task-alb-xxx.us-east-1... │
  │              │             │         │ target_group_arn: arn:aws:elasticloadbalancing:...   │
  ├──────────────┼─────────────┼─────────┼──────────────────────────────────────────────────────┤
  │ task_service │ ecs-fargate │ created │ name: task-manager-dev-task-service                  │
  │              │             │         │ arn: arn:aws:ecs:us-east-1:...:service/...           │
  │              │             │         │ cluster: task-manager-dev                            │
  └──────────────┴─────────────┴─────────┴──────────────────────────────────────────────────────┘
```

The `task_alb → endpoint` value is the public DNS name of the load balancer. You can `curl` it once the ECS service has a running task:

```bash
curl http://$(infrakit status | grep endpoint | head -1 | awk '{print $2}')
```

### Verify resource tags

Every resource created by InfraKit is tagged with:

| Tag key | Value |
|---------|-------|
| `infrakit:project` | `task-manager` |
| `infrakit:env` | `dev` |
| `infrakit:version` | `0.3.0` |
| `infrakit:managed-by` | `infrakit` |

Check tags on the DynamoDB table:

```bash
aws dynamodb list-tags-of-resource \
  --resource-arn $(aws dynamodb describe-table \
    --table-name task-manager-dev-task-table \
    --query 'Table.TableArn' --output text)
```

## 4. Update the stack

InfraKit's `plan` command shows structural changes: resources to add or remove. Edit `infrakit.yaml` to add a new resource, then preview and apply.

### Example: add an S3 bucket for file attachments

Add this block to `infrakit.yaml` under `services:`:

```yaml
  attachments_bucket:
    type: s3
    versioning: false
```

Run `plan` to see the diff:

```
$ infrakit plan

  Plan
  ┌─────────────────────┬──────────┬────────┐
  │ Resource            │ Type     │ Action │
  ├─────────────────────┼──────────┼────────┤
  │ attachments_bucket  │ s3       │ create │
  └─────────────────────┴──────────┴────────┘

  Plan: 1 to create, 0 to delete.
```

The four existing resources are not listed — they are already in state and will not be touched.

Apply the change:

```
$ infrakit deploy --auto-approve

  = task_table (dynamodb) — no changes
  = task_role (iam-role) — no changes
  = task_alb (alb) — no changes
  = task_service (ecs-fargate) — no changes
  + attachments_bucket (s3) — creating

  Deploy complete.
```

### Example: remove a resource

Delete the `attachments_bucket` block from `infrakit.yaml`, then plan:

```
$ infrakit plan

  Plan
  ┌─────────────────────┬──────────┬────────┐
  │ Resource            │ Type     │ Action │
  ├─────────────────────┼──────────┼────────┤
  │ attachments_bucket  │ s3       │ delete │
  └─────────────────────┴──────────┴────────┘

  Plan: 0 to create, 1 to delete.
```

> **Note:** `infrakit plan` does not delete resources — it only shows what `deploy` would do. Resources removed from config are cleaned up by `infrakit deploy` (which deletes state-tracked resources absent from config) or explicitly via `infrakit destroy`.

### What plan does NOT detect

`plan` reports structural changes only (add / remove resources). It does not yet detect configuration drift within a resource (e.g., changing `desired_count` from `1` to `2`). Full drift detection — comparing live AWS state against config — is coming in Phase 4 via `infrakit drift`.

## 5. Destroy

Tears down all resources in reverse dependency order:

```
$ infrakit destroy --auto-approve

  - task_service (ecs-fargate) — destroying
  - task_alb (alb) — destroying
  - task_role (iam-role) — destroying
  - task_table (dynamodb) — destroying

  Destroy complete.
```

## Remote state (team / CI use)

By default, state is stored locally in `.infrakit/state.json`. For team environments or CI/CD pipelines, switch to S3 + DynamoDB:

1. Create the state bucket and lock table (one-time setup):

```bash
aws s3 mb s3://my-infrakit-state --region us-east-1
aws dynamodb create-table \
  --table-name infrakit-locks \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-1
```

2. Add the `state` block to `infrakit.yaml`:

```yaml
state:
  backend: s3
  bucket: my-infrakit-state
  lock_table: infrakit-locks
```

Two simultaneous deploys will now contend for the DynamoDB lock — only one proceeds at a time.

## Phase 4 preview — drift detection

Once deployed, simulate an out-of-band change by deleting the DynamoDB table directly from the AWS console, then run:

```bash
infrakit drift   # coming in Phase 4
```

InfraKit will compare the live AWS state against the state file and report the deleted resource. The `task-manager` stack is the intended drift detection demo target for Phase 4.

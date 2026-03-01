"""IAM role provider."""

from __future__ import annotations

import json
from typing import Any

from botocore.exceptions import ClientError

from infrakit.core.session import AWSSession
from infrakit.providers.base import ResourceProvider
from infrakit.schema.models import IAMRoleResource
from infrakit.utils.tags import standard_tags, to_boto3_tags


class IAMProvider(ResourceProvider):
    config: IAMRoleResource

    def __init__(
        self,
        name: str,
        config: IAMRoleResource,
        project: str,
        env: str,
        region: str = "us-east-1",
    ) -> None:
        super().__init__(name, config, project, env, region)
        self._client = AWSSession.client("iam", region_name=region)

    # ------------------------------------------------------------------
    # Interface implementation
    # ------------------------------------------------------------------

    def exists(self) -> bool:
        try:
            self._client.get_role(RoleName=self.physical_name)
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("NoSuchEntityException", "NoSuchEntity"):
                return False
            raise

    def create(self) -> dict[str, Any]:
        trust_policy = self._trust_policy(self.config.assumed_by)

        resp = self._client.create_role(
            RoleName=self.physical_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Tags=to_boto3_tags(standard_tags(self.project, self.env)),
        )
        role = resp["Role"]

        self._attach_policies(role["RoleName"])

        self.logger.info("Created IAM role: %s", self.physical_name)
        return {
            "name": role["RoleName"],
            "arn": role["Arn"],
        }

    def delete(self) -> None:
        if not self.exists():
            self.logger.info("Role %s already absent.", self.physical_name)
            return

        # Detach all managed policies first
        paginator = self._client.get_paginator("list_attached_role_policies")
        for page in paginator.paginate(RoleName=self.physical_name):
            for policy in page["AttachedPolicies"]:
                self._client.detach_role_policy(
                    RoleName=self.physical_name,
                    PolicyArn=policy["PolicyArn"],
                )

        # Delete any inline policies
        paginator2 = self._client.get_paginator("list_role_policies")
        for page in paginator2.paginate(RoleName=self.physical_name):
            for policy_name in page["PolicyNames"]:
                self._client.delete_role_policy(
                    RoleName=self.physical_name,
                    PolicyName=policy_name,
                )

        self._client.delete_role(RoleName=self.physical_name)
        self.logger.info("Deleted IAM role: %s", self.physical_name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _trust_policy(assumed_by: str) -> dict[str, Any]:
        return {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": assumed_by},
                    "Action": "sts:AssumeRole",
                }
            ],
        }

    def _attach_policies(self, role_name: str) -> None:
        for idx, policy in enumerate(self.config.policies):
            if isinstance(policy, str):
                # Managed policy ARN
                self._client.attach_role_policy(
                    RoleName=role_name,
                    PolicyArn=policy,
                )
            elif isinstance(policy, dict) and "inline" in policy:
                # Inline policy: {"inline": {"action:*": "resource"}}
                inline = policy["inline"]
                policy_doc = {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": [a.strip() for a in actions.split(",")],
                            "Resource": resource,
                        }
                        for actions, resource in inline.items()
                    ],
                }
                self._client.put_role_policy(
                    RoleName=role_name,
                    PolicyName=f"{role_name}-inline-{idx}",
                    PolicyDocument=json.dumps(policy_doc),
                )

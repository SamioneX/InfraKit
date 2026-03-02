"""S3 bucket provider."""

from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError

from infrakit.core.session import AWSSession
from infrakit.providers.base import ResourceProvider
from infrakit.schema.models import S3Resource
from infrakit.utils.tags import standard_tags, to_boto3_tags


class S3Provider(ResourceProvider):
    config: S3Resource

    def __init__(
        self,
        name: str,
        config: S3Resource,
        project: str,
        env: str,
        region: str = "us-east-1",
    ) -> None:
        super().__init__(name, config, project, env, region)
        self._client = AWSSession.client("s3", region_name=region)

    # ------------------------------------------------------------------
    # Interface implementation
    # ------------------------------------------------------------------

    @property
    def _bucket_name(self) -> str:
        """S3 bucket names only allow lowercase alphanumeric and hyphens (no underscores)."""
        return self.physical_name.replace("_", "-").lower()

    def exists(self) -> bool:
        try:
            self._client.head_bucket(Bucket=self._bucket_name)
            return True
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("404", "NoSuchBucket"):
                return False
            raise

    def create(self) -> dict[str, Any]:
        cfg = self.config
        bucket_name = self._bucket_name

        kwargs: dict[str, Any] = {"Bucket": bucket_name}
        # us-east-1 must NOT pass CreateBucketConfiguration
        if self.region != "us-east-1":
            kwargs["CreateBucketConfiguration"] = {"LocationConstraint": self.region}

        self._client.create_bucket(**kwargs)

        self._client.put_bucket_tagging(
            Bucket=bucket_name,
            Tagging={"TagSet": to_boto3_tags(standard_tags(self.project, self.env))},
        )

        if cfg.versioning:
            self._client.put_bucket_versioning(
                Bucket=bucket_name,
                VersioningConfiguration={"Status": "Enabled"},
            )

        if not cfg.public:
            self._client.put_public_access_block(
                Bucket=bucket_name,
                PublicAccessBlockConfiguration={
                    "BlockPublicAcls": True,
                    "IgnorePublicAcls": True,
                    "BlockPublicPolicy": True,
                    "RestrictPublicBuckets": True,
                },
            )

        if cfg.lifecycle_days:
            self._client.put_bucket_lifecycle_configuration(
                Bucket=bucket_name,
                LifecycleConfiguration={
                    "Rules": [
                        {
                            "ID": "expire-objects",
                            "Status": "Enabled",
                            "Expiration": {"Days": cfg.lifecycle_days},
                            "Filter": {"Prefix": ""},
                        }
                    ]
                },
            )

        self.logger.info("Created S3 bucket: %s", bucket_name)
        account_id = self._get_account_id()
        arn = f"arn:aws:s3:::{bucket_name}"
        return {
            "name": bucket_name,
            "arn": arn,
            "bucket_url": f"https://{bucket_name}.s3.{self.region}.amazonaws.com",
            "account_id": account_id,
        }

    def delete(self) -> None:
        if not self.exists():
            self.logger.info("Bucket %s already absent.", self._bucket_name)
            return

        # Must empty the bucket before deletion
        self._empty_bucket(self._bucket_name)
        self._client.delete_bucket(Bucket=self._bucket_name)
        self.logger.info("Deleted S3 bucket: %s", self._bucket_name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _empty_bucket(self, bucket_name: str) -> None:
        s3 = AWSSession.resource("s3", region_name=self.region)
        bucket = s3.Bucket(bucket_name)
        bucket.objects.all().delete()

    def _get_account_id(self) -> str:
        sts = AWSSession.client("sts", region_name=self.region)
        return str(sts.get_caller_identity()["Account"])

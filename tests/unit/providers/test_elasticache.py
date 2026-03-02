"""Unit tests for the ElastiCache provider."""

from __future__ import annotations

from infrakit.providers.elasticache import ElastiCacheProvider
from infrakit.schema.models import ElastiCacheResource


def _make_provider(mocked_aws: None, engine: str = "redis") -> ElastiCacheProvider:
    cfg = ElastiCacheResource(type="elasticache", engine=engine, node_type="cache.t3.micro", num_nodes=1)  # type: ignore[arg-type]
    return ElastiCacheProvider("cache", cfg, project="myapp", env="dev")


class TestElastiCacheProvider:
    def test_physical_name(self, mocked_aws: None) -> None:
        p = _make_provider(mocked_aws)
        assert p.physical_name == "myapp-dev-cache"

    def test_cluster_id_truncated_to_20(self, mocked_aws: None) -> None:
        cfg = ElastiCacheResource(type="elasticache", engine="redis", node_type="cache.t3.micro", num_nodes=1)  # type: ignore[arg-type]
        p = ElastiCacheProvider("verylongresourcename", cfg, project="myproject", env="prod")
        assert len(p._cluster_id) <= 20

    def test_exists_false_when_no_cluster(self, mocked_aws: None) -> None:
        p = _make_provider(mocked_aws)
        assert p.exists() is False

    def test_create_redis_cluster(self, mocked_aws: None) -> None:
        p = _make_provider(mocked_aws, engine="redis")
        outputs = p.create()
        assert "name" in outputs
        assert "endpoint" in outputs
        assert "port" in outputs
        assert "arn" in outputs
        assert outputs["port"] == "6379"

    def test_exists_true_after_create(self, mocked_aws: None) -> None:
        p = _make_provider(mocked_aws)
        p.create()
        assert p.exists() is True

    def test_create_memcached_cluster(self, mocked_aws: None) -> None:
        cfg = ElastiCacheResource(type="elasticache", engine="memcached", node_type="cache.t3.micro", num_nodes=1)  # type: ignore[arg-type]
        p = ElastiCacheProvider("memcache", cfg, project="myapp", env="dev")
        outputs = p.create()
        assert outputs["port"] == "11211"

    def test_delete_removes_cluster(self, mocked_aws: None) -> None:
        p = _make_provider(mocked_aws)
        p.create()
        p.delete()
        assert p.exists() is False

    def test_delete_when_not_exists_is_safe(self, mocked_aws: None) -> None:
        p = _make_provider(mocked_aws)
        p.delete()  # should not raise

    def test_outputs_contain_arn(self, mocked_aws: None) -> None:
        p = _make_provider(mocked_aws)
        outputs = p.create()
        assert "arn:aws:elasticache" in outputs["arn"]
        assert p._cluster_id in outputs["arn"]

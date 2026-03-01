"""Standard resource tagging helpers.

Every resource InfraKit provisions must carry these tags so that
resources can be identified and cleaned up even if state is lost.
"""

from __future__ import annotations


def standard_tags(project: str, env: str, version: str = "0.1.0") -> dict[str, str]:
    """Return the mandatory InfraKit tag set."""
    return {
        "infrakit:project": project,
        "infrakit:env": env,
        "infrakit:version": version,
        "infrakit:managed-by": "infrakit",
    }


def to_boto3_tags(tags: dict[str, str]) -> list[dict[str, str]]:
    """Convert a plain dict to the ``[{"Key": k, "Value": v}]`` format
    that most boto3 APIs expect."""
    return [{"Key": k, "Value": v} for k, v in tags.items()]

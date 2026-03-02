"""Simple Lambda handler for the InfraKit hello-api example."""

import json
import os


def handler(event: dict, context: object) -> dict:
    greeting = os.environ.get("GREETING", "Hello from InfraKit!")
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "/")
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(
            {
                "message": greeting,
                "method": method,
                "path": path,
            }
        ),
    }

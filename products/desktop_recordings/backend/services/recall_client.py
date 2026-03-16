from typing import Any

import requests


class RecallAIClient:
    """Client for Recall.ai API - only used to create SDK upload tokens"""

    def __init__(self, api_key: str, api_url: str = "https://us-west-2.recall.ai"):
        self.api_key = api_key
        self.base_url = api_url.rstrip("/")

    def create_sdk_upload(self, recording_config: dict[str, Any] | None = None) -> dict[str, Any]:
        """Create SDK upload and return upload token for Array desktop app"""
        payload: dict[str, Any] = {}
        if recording_config:
            payload["recording_config"] = recording_config

        response = requests.post(
            f"{self.base_url}/api/v1/sdk-upload/",
            json=payload,
            headers={"Authorization": f"Token {self.api_key}"},
        )
        response.raise_for_status()
        return response.json()

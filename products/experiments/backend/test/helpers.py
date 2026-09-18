from typing import Any

from rest_framework.response import Response
from rest_framework.test import APIClient


def create_experiment_via_api(client: APIClient, team_id: int, ff_key: str, **extra_fields: Any) -> Response:
    return client.post(
        f"/api/projects/{team_id}/experiments/",
        {
            "name": "Test Experiment",
            "description": "",
            "start_date": "2021-12-01T10:23",
            "end_date": None,
            "feature_flag_key": ff_key,
            "parameters": None,
            "filters": {
                "events": [
                    {"order": 0, "id": "$pageview"},
                    {"order": 1, "id": "$pageleave"},
                ],
                "properties": [],
            },
            **extra_fields,
        },
    )

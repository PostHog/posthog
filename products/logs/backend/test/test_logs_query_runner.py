import json
from unittest.mock import ANY, patch

from django.core.cache import cache
from django.test.client import Client
from rest_framework import status

from posthog.models import FeatureFlag, Person
from posthog.models.team.team_caching import set_team_in_cache
from posthog.test.base import (
    APIBaseTest,
    BaseTest,
    QueryMatchingTest,
    snapshot_postgres_queries,
)
from products.logs.backend.logs_query_runner import LogsQueryRunner

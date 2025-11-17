import urllib.parse

from django.conf import settings

import requests
import structlog
from rest_framework import viewsets
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models.integration import GitHubIntegration, Integration

logger = structlog.get_logger(__name__)


def prepare_github_search_query(q):
    if not q:
        return ""

    result = []
    in_quotes = False
    quote_char = None

    for char in q:
        if char in ('"', "'", "`") and not in_quotes:
            in_quotes = True
            quote_char = char
            result.append(char)
        elif char == quote_char and in_quotes:
            in_quotes = False
            quote_char = None
            result.append(char)
        elif in_quotes:
            result.append(char)
        elif char in ".,:;/\\=*!?#$&+^|~<>(){}[]":
            result.append(" ")
        else:
            result.append(char)

    return " ".join("".join(result).split())


def get_github_file_url(code_sample: str, token: str, owner: str, repository: str, file_name: str) -> str | None:
    """Search GitHub code using the Code Search API. Returns URL to first match or None."""
    code_query = prepare_github_search_query(code_sample)
    search_query = f"{code_query} repo:{owner}/{repository} filename:{file_name}"
    encoded_query = urllib.parse.quote(search_query)
    url = f"https://api.github.com/search/code?q={encoded_query}"

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.text-match+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            items = data.get("items", [])
            if items:
                return items[0].get("html_url")
            return None
        else:
            logger.warning("github_code_search_failed", status_code=response.status_code)
            return None
    except requests.exceptions.RequestException as e:
        logger.exception("github_code_search_request_failed", error=str(e))
        return None


class GitProviderFileLinksViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "error_tracking"

    @action(methods=["GET"], detail=False, url_path="resolve_github")
    def resolve_github(self, request, **kwargs):
        owner = request.GET.get("owner")
        repository = request.GET.get("repository")
        code_sample = request.GET.get("code_sample")
        file_name = request.GET.get("file_name")

        if not owner or not repository or not code_sample or not file_name:
            return Response({"found": False, "error": "owner, repository, code_sample, and file_name are required"})

        url = None

        # Try with posthogs token first (public repos)
        if settings.GITHUB_TOKEN:
            url = get_github_file_url(
                code_sample=code_sample,
                token=settings.GITHUB_TOKEN,
                owner=owner,
                repository=repository,
                file_name=file_name,
            )
            if url:
                return Response({"found": True, "url": url})

        # Try with assigned github integration (private repos)
        integration = Integration.objects.filter(team_id=self.team.id, kind="github").first()

        if integration:
            github = GitHubIntegration(integration)

            if github.access_token_expired():
                github.refresh_access_token()

            token = github.integration.sensitive_config.get("access_token")
            if token:
                url = get_github_file_url(
                    code_sample=code_sample, token=token, owner=owner, repository=repository, file_name=file_name
                )
                if url:
                    return Response({"found": True, "url": url})

        return Response({"found": False})

import urllib.parse

from django.conf import settings

import requests
import structlog
from rest_framework import viewsets
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models.integration import GitHubIntegration, GitLabIntegration, Integration

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


def prepare_gitlab_search_query(q):
    """Sanitize code sample for GitLab search by removing special characters but NOT preserving quotes."""
    if not q:
        return ""

    result = []
    for char in q:
        # Remove ALL special characters including quotes/backticks
        if char in ".,:;/\\=*!?#$&+^|~<>(){}[]\"'`":
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


def get_gitlab_file_url(
    code_sample: str, token: str, owner: str, repository: str, file_name: str, gitlab_url: str = "https://gitlab.com"
) -> str | None:
    """Search GitLab code using the Search API. Returns URL to first match or None."""
    code_query = prepare_gitlab_search_query(code_sample)
    project_path = f"{owner}/{repository}"
    encoded_project_path = urllib.parse.quote(project_path, safe="")
    search_scope = "blobs"
    encoded_search = urllib.parse.quote(code_query)
    url = f"{gitlab_url}/api/v4/projects/{encoded_project_path}/search?scope={search_scope}&search={encoded_search}"

    headers = {
        "PRIVATE-TOKEN": token,
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            if data:
                for item in data:
                    item_path = item.get("path", "")
                    if file_name in item_path:
                        ref = item.get("ref", "")
                        if ref and item_path:
                            return f"{gitlab_url}/{owner}/{repository}/-/blob/{ref}/{item_path}"
                return None
            return None
        else:
            logger.warning("gitlab_code_search_failed", status_code=response.status_code, response_text=response.text)
            return None
    except requests.exceptions.RequestException as e:
        logger.exception("gitlab_code_search_request_failed", error=str(e))
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

    @action(methods=["GET"], detail=False, url_path="resolve_gitlab")
    def resolve_gitlab(self, request, **kwargs):
        owner = request.GET.get("owner")
        repository = request.GET.get("repository")
        code_sample = request.GET.get("code_sample")
        file_name = request.GET.get("file_name")

        if not owner or not repository or not code_sample or not file_name:
            return Response({"found": False, "error": "owner, repository, code_sample, and file_name are required"})

        url = None

        integration = Integration.objects.filter(team_id=self.team.id, kind="gitlab").first()

        if integration:
            gitlab = GitLabIntegration(integration)
            hostname = gitlab.hostname
            token = gitlab.integration.sensitive_config.get("access_token")

            if token:
                url = get_gitlab_file_url(
                    code_sample=code_sample,
                    token=token,
                    owner=owner,
                    repository=repository,
                    file_name=file_name,
                    gitlab_url=hostname,
                )
                if url:
                    return Response({"found": True, "url": url})

        return Response({"found": False})

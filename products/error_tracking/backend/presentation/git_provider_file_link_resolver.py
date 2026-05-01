import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.conf import settings

import requests
import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.response import Response

from posthog.schema import ProductKey

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models.integration import GitHubIntegration, GitLabIntegration, Integration

logger = structlog.get_logger(__name__)

MISSING_REQUIRED_PARAMS_ERROR = "owner, repository, code_sample, and file_name are required"


class GitProviderFileLinkResolveQuerySerializer(serializers.Serializer):
    owner = serializers.CharField(help_text="Repository owner or namespace.")
    repository = serializers.CharField(help_text="Repository name.")
    code_sample = serializers.CharField(help_text="Code snippet to search for in repository files.")
    file_name = serializers.CharField(help_text="File name to match in search results.")


class GitProviderFileLinkResolveResponseSerializer(serializers.Serializer):
    found = serializers.BooleanField(help_text="Whether a matching file URL was found.")
    url = serializers.CharField(required=False, help_text="Resolved URL for the matching file.")
    error = serializers.CharField(required=False, help_text="Error message when input parameters are invalid.")


def prepare_github_search_query(q: str | None) -> str:
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


def prepare_gitlab_search_query(q: str | None) -> str:
    """Sanitize code sample for GitLab search by removing special characters."""
    if not q:
        return ""

    result = []
    for char in q:
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

        logger.warning("github_code_search_failed", status_code=response.status_code)
        return None
    except Exception as error:
        logger.exception("github_code_search_request_failed", error=str(error))
        return None


def get_gitlab_file_url(
    code_sample: str, token: str, owner: str, repository: str, file_name: str, gitlab_url: str = "https://gitlab.com"
) -> str | None:
    """Search GitLab code using the Search API. Returns URL to first match or None."""
    project_path = f"{owner}/{repository}"
    encoded_project_path = urllib.parse.quote(project_path, safe="")
    search_scope = "blobs"

    headers = {
        "PRIVATE-TOKEN": token,
        "Content-Type": "application/json",
    }

    # GitLab search behavior varies depending on repo visibility and current plan. Seems like under some conditions
    # the search uses different engine - it is not documented so I decided to run multiple searches just to be safe
    search_variants = [
        code_sample.strip(),
        prepare_gitlab_search_query(code_sample),
    ]

    def execute_single_search_variant(search_query: str) -> str | None:
        if not search_query:
            return None

        encoded_search = urllib.parse.quote(search_query)
        url = f"{gitlab_url}/api/v4/projects/{encoded_project_path}/search?scope={search_scope}&search={encoded_search}"

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
        except Exception as error:
            logger.exception("gitlab_code_search_request_failed", error=str(error))

        return None

    with ThreadPoolExecutor(max_workers=len(search_variants)) as executor:
        future_to_variant = {
            executor.submit(execute_single_search_variant, variant): variant for variant in search_variants
        }

        for future in as_completed(future_to_variant):
            resolved_url = future.result()
            if resolved_url:
                return resolved_url

    return None


@extend_schema(tags=[ProductKey.ERROR_TRACKING])
class GitProviderFileLinksViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "error_tracking"

    @extend_schema(
        parameters=[GitProviderFileLinkResolveQuerySerializer],
        responses={200: OpenApiResponse(response=GitProviderFileLinkResolveResponseSerializer)},
    )
    @action(methods=["GET"], detail=False, url_path="resolve_github")
    def resolve_github(self, request, **kwargs):
        serializer = GitProviderFileLinkResolveQuerySerializer(data=request.GET)
        if not serializer.is_valid():
            return Response({"found": False, "error": MISSING_REQUIRED_PARAMS_ERROR})

        owner = serializer.validated_data["owner"]
        repository = serializer.validated_data["repository"]
        code_sample = serializer.validated_data["code_sample"]
        file_name = serializer.validated_data["file_name"]

        url = None

        # Try with PostHog's token first (public repos).
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

        # Try with assigned GitHub integration (private repos).
        integration = Integration.objects.filter(team_id=self.team.id, kind="github").first()

        if integration:
            github = GitHubIntegration(integration)

            if github.access_token_expired():
                github.refresh_access_token()

            token = github.integration.sensitive_config.get("access_token")
            if token:
                url = get_github_file_url(
                    code_sample=code_sample,
                    token=token,
                    owner=owner,
                    repository=repository,
                    file_name=file_name,
                )
                if url:
                    return Response({"found": True, "url": url})

        return Response({"found": False})

    @extend_schema(
        parameters=[GitProviderFileLinkResolveQuerySerializer],
        responses={200: OpenApiResponse(response=GitProviderFileLinkResolveResponseSerializer)},
    )
    @action(methods=["GET"], detail=False, url_path="resolve_gitlab")
    def resolve_gitlab(self, request, **kwargs):
        serializer = GitProviderFileLinkResolveQuerySerializer(data=request.GET)
        if not serializer.is_valid():
            return Response({"found": False, "error": MISSING_REQUIRED_PARAMS_ERROR})

        owner = serializer.validated_data["owner"]
        repository = serializer.validated_data["repository"]
        code_sample = serializer.validated_data["code_sample"]
        file_name = serializer.validated_data["file_name"]

        # Try with PostHog's token first (public repos on gitlab.com).
        if settings.GITLAB_TOKEN:
            url = get_gitlab_file_url(
                code_sample=code_sample,
                token=settings.GITLAB_TOKEN,
                owner=owner,
                repository=repository,
                file_name=file_name,
                gitlab_url="https://gitlab.com",
            )

            if url:
                return Response({"found": True, "url": url})

        # Try with team GitLab integrations (private repos and self-hosted).
        integrations = Integration.objects.filter(team_id=self.team.id, kind="gitlab")

        if not integrations:
            return Response({"found": False})

        def try_integration(integration: Integration) -> str | None:
            try:
                gitlab = GitLabIntegration(integration)
                hostname = gitlab.hostname
                token = gitlab.integration.sensitive_config.get("access_token")

                if token:
                    return get_gitlab_file_url(
                        code_sample=code_sample,
                        token=token,
                        owner=owner,
                        repository=repository,
                        file_name=file_name,
                        gitlab_url=hostname,
                    )
            except Exception:
                return None

            return None

        with ThreadPoolExecutor(max_workers=min(len(integrations), 5)) as executor:
            future_to_integration = {
                executor.submit(try_integration, integration): integration for integration in integrations
            }

            for future in as_completed(future_to_integration):
                url = future.result()
                if url:
                    return Response({"found": True, "url": url})

        return Response({"found": False})

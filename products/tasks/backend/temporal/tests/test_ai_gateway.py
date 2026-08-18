import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from products.tasks.backend.models import Task
from products.tasks.backend.temporal.ai_gateway import mint_signals_scoped_token

MINT_SETTINGS = {"AI_GATEWAY_MINT_URL": "https://ai-gateway.example.com"}


def _task(origin_product: Task.OriginProduct, internal: bool = False) -> MagicMock:
    return MagicMock(id="task-id", team_id=123, origin_product=origin_product, internal=internal)


def _token_row(user_id: int | None = 42) -> MagicMock:
    return MagicMock(user_id=user_id)


def _mint_response(token: str | None = "phe_minted") -> MagicMock:
    response = MagicMock()
    response.json.return_value = {"token": token} if token else {}
    return response


@pytest.mark.parametrize(
    ("origin_product", "internal", "expected"),
    [
        (Task.OriginProduct.SIGNAL_REPORT, False, "phe_minted"),
        (Task.OriginProduct.SIGNALS_CHAT, False, "phe_minted"),
        (Task.OriginProduct.SIGNAL_REPORT, True, None),
        (Task.OriginProduct.SIGNALS_SCOUT, False, None),
        (Task.OriginProduct.USER_CREATED, False, None),
    ],
)
@patch("products.tasks.backend.temporal.ai_gateway.requests.post")
@patch("products.tasks.backend.temporal.ai_gateway.project_gateway_credential")
@patch("products.tasks.backend.temporal.ai_gateway.find_oauth_access_token")
def test_mints_only_for_interactive_signals_runs(
    mock_find: MagicMock,
    mock_project: MagicMock,
    mock_post: MagicMock,
    origin_product: Task.OriginProduct,
    internal: bool,
    expected: str | None,
) -> None:
    mock_find.return_value = _token_row()
    mock_post.return_value = _mint_response()

    with override_settings(**MINT_SETTINGS):
        assert mint_signals_scoped_token(_task(origin_product, internal), "pha_token") == expected

    assert mock_post.called is (expected is not None)


@patch("products.tasks.backend.temporal.ai_gateway.requests.post")
@patch("products.tasks.backend.temporal.ai_gateway.find_oauth_access_token")
def test_no_mint_url_disables_minting_entirely(mock_find: MagicMock, mock_post: MagicMock) -> None:
    with override_settings(AI_GATEWAY_MINT_URL=None):
        assert mint_signals_scoped_token(_task(Task.OriginProduct.SIGNAL_REPORT), "pha_token") is None

    mock_find.assert_not_called()
    mock_post.assert_not_called()


@patch("products.tasks.backend.temporal.ai_gateway.requests.post")
@patch("products.tasks.backend.temporal.ai_gateway.project_gateway_credential")
@patch("products.tasks.backend.temporal.ai_gateway.find_oauth_access_token")
def test_mint_pins_budget_attribution_and_cap_on_the_wire(
    mock_find: MagicMock, mock_project: MagicMock, mock_post: MagicMock
) -> None:
    mock_find.return_value = _token_row(user_id=42)
    mock_post.return_value = _mint_response()

    with override_settings(**MINT_SETTINGS, TASKS_SIGNALS_INTERACTIVE_COST_CAP_USD="50"):
        assert mint_signals_scoped_token(_task(Task.OriginProduct.SIGNAL_REPORT), "pha_token") == "phe_minted"

    assert mock_post.call_args.args == ("https://ai-gateway.example.com/v1/tokens",)
    payload = mock_post.call_args.kwargs["json"]
    assert payload["cap_usd"] == "50"
    assert payload["ttl_seconds"] == 6 * 60 * 60
    assert payload["product"] == "signals_interactive"
    assert payload["user"] == "42"
    assert payload["obo"] == "123"


@patch("products.tasks.backend.temporal.ai_gateway.requests.post")
@patch("products.tasks.backend.temporal.ai_gateway.project_gateway_credential")
@patch("products.tasks.backend.temporal.ai_gateway.find_oauth_access_token")
def test_oauth_minting_projects_the_credential_before_the_mint(
    mock_find: MagicMock, mock_project: MagicMock, mock_post: MagicMock
) -> None:
    # Without the synchronous projection the mint races the post-commit Celery write of the
    # credential blob and the gateway 401s the brand-new token.
    row = _token_row()
    mock_find.return_value = row
    mock_post.return_value = _mint_response()

    with override_settings(**MINT_SETTINGS, AI_GATEWAY_MINT_CREDENTIAL=None):
        mint_signals_scoped_token(_task(Task.OriginProduct.SIGNAL_REPORT), "pha_token")

    mock_project.assert_called_once_with(row)
    assert mock_post.call_args.kwargs["headers"] == {"Authorization": "Bearer pha_token"}


@patch("products.tasks.backend.temporal.ai_gateway.requests.post")
@patch("products.tasks.backend.temporal.ai_gateway.project_gateway_credential")
@patch("products.tasks.backend.temporal.ai_gateway.find_oauth_access_token")
def test_configured_mint_credential_skips_projection_and_signs_the_mint(
    mock_find: MagicMock, mock_project: MagicMock, mock_post: MagicMock
) -> None:
    mock_find.return_value = _token_row()
    mock_post.return_value = _mint_response()

    with override_settings(**MINT_SETTINGS, AI_GATEWAY_MINT_CREDENTIAL="phs_secret"):
        mint_signals_scoped_token(_task(Task.OriginProduct.SIGNAL_REPORT), "pha_token")

    mock_project.assert_not_called()
    assert mock_post.call_args.kwargs["headers"] == {"Authorization": "Bearer phs_secret"}


@pytest.mark.parametrize(
    ("post_effect", "response"),
    [
        (Exception("gateway down"), None),
        (None, _mint_response(token=None)),
    ],
)
@patch("products.tasks.backend.temporal.ai_gateway.requests.post")
@patch("products.tasks.backend.temporal.ai_gateway.project_gateway_credential")
@patch("products.tasks.backend.temporal.ai_gateway.find_oauth_access_token")
def test_mint_failures_fall_back_to_none_instead_of_failing_the_run(
    mock_find: MagicMock,
    mock_project: MagicMock,
    mock_post: MagicMock,
    post_effect: Exception | None,
    response: MagicMock | None,
) -> None:
    mock_find.return_value = _token_row()
    if post_effect is not None:
        mock_post.side_effect = post_effect
    else:
        mock_post.return_value = response

    with override_settings(**MINT_SETTINGS):
        assert mint_signals_scoped_token(_task(Task.OriginProduct.SIGNAL_REPORT), "pha_token") is None


@patch("products.tasks.backend.temporal.ai_gateway.requests.post")
@patch("products.tasks.backend.temporal.ai_gateway.project_gateway_credential")
@patch("products.tasks.backend.temporal.ai_gateway.find_oauth_access_token")
def test_missing_oauth_row_skips_the_mint(mock_find: MagicMock, mock_project: MagicMock, mock_post: MagicMock) -> None:
    mock_find.return_value = None

    with override_settings(**MINT_SETTINGS):
        assert mint_signals_scoped_token(_task(Task.OriginProduct.SIGNAL_REPORT), "pha_token") is None

    mock_post.assert_not_called()

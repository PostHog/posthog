"""The cut step's one model call, through the ai-gateway with a short-lived token minted for it.

Any failure answers None, which makes `decide_cuts` keep every owner. Routing must never wait on or
fail over a missing gateway, a missing connecting user, a refused mint or an API error.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

import httpx
import structlog
from anthropic import Anthropic, BadRequestError
from anthropic.types import JSONOutputFormatParam, Message, OutputConfigParam

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import resolve_ai_gateway_config

from products.stamphog.backend.logic.gateway_tokens import (
    STAMPHOG_AI_PRODUCT,
    active_user,
    gateway_root,
    is_legacy_stamphog_route,
    mint_scoped_token,
    revoke_scoped_token,
)
from products.stamphog.backend.logic.routing.cut import CUT_MODEL

logger = structlog.get_logger(__name__)

# One small call reads at most the capped diff, so this cap and TTL sit far below the reviewer's.
# They bound what a leaked token can spend, so do not widen them without a cost reason.
ROUTING_TOKEN_CAP_USD = "0.25"
ROUTING_TOKEN_TTL_SECONDS = 300
# A timeout keeps every owner, so this only bounds how long the author waits for the review requests.
# It sits above the slowest call of the offline evaluation.
_CALL_TIMEOUT_SECONDS = 30
_MAX_OUTPUT_TOKENS = 16_000


@frozen
class CutUsage:
    input_tokens: int
    output_tokens: int


def _parse_answer(text: str) -> Mapping[str, object] | None:
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _create(client: Anthropic, system_prompt: str, user_prompt: str, output_config: OutputConfigParam) -> Message:
    return client.messages.create(
        model=CUT_MODEL,
        max_tokens=_MAX_OUTPUT_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        output_config=output_config,
    )


def _create_with_effort_fallback(
    client: Anthropic, system_prompt: str, user_prompt: str, output_format: JSONOutputFormatParam
) -> Message:
    try:
        return _create(client, system_prompt, user_prompt, {"effort": "medium", "format": output_format})
    except BadRequestError as exc:
        if "effort" not in str(exc):
            raise
    # The offline evaluation made the same fallback for a model without the effort setting.
    return _create(client, system_prompt, user_prompt, {"format": output_format})


class GatewayCutModel:
    """A `CutModelCall` for one routing run.

    After the call, `sent_request` says whether a request reached the gateway, and `usage` holds
    the token counts of an answer.
    """

    def __init__(self, *, team_id: int, connected_by_user_id: int | None, attribution: Mapping[str, object]) -> None:
        self._team_id = team_id
        self._connected_by_user_id = connected_by_user_id
        self._attribution = attribution
        self.sent_request = False
        self.usage: CutUsage | None = None

    def __call__(
        self, system_prompt: str, user_prompt: str, schema: Mapping[str, object]
    ) -> Mapping[str, object] | None:
        gateway = resolve_ai_gateway_config()
        if gateway is None or is_legacy_stamphog_route(gateway.url):
            logger.info("stamphog_reviewer_routing_no_gateway", team_id=self._team_id)
            return None
        user = active_user(self._connected_by_user_id)
        if user is None:
            logger.info("stamphog_reviewer_routing_no_connecting_user", team_id=self._team_id)
            return None
        try:
            token = mint_scoped_token(
                gateway,
                team_id=self._team_id,
                user=user,
                cap_usd=ROUTING_TOKEN_CAP_USD,
                ttl_seconds=ROUTING_TOKEN_TTL_SECONDS,
                allowed_models=[CUT_MODEL],
            )
        except Exception as exc:  # noqa: BLE001 - the cut is optional, so a mint failure keeps every owner
            logger.warning("stamphog_reviewer_routing_mint_failed", error_type=type(exc).__name__)
            return None
        try:
            return self._ask(gateway_root(gateway), token, system_prompt, user_prompt, schema)
        finally:
            outcome = revoke_scoped_token(gateway, token)
            if outcome != "ok":
                logger.warning("stamphog_reviewer_routing_revoke_failed", outcome=outcome)

    def _ask(
        self, root: str, token: str, system_prompt: str, user_prompt: str, schema: Mapping[str, object]
    ) -> Mapping[str, object] | None:
        properties = json.dumps({"ai_product": STAMPHOG_AI_PRODUCT, **self._attribution}, separators=(",", ":"))
        client = Anthropic(
            base_url=root,
            # The gateway accepts the token as either header, and the engine sends both.
            api_key=token,
            auth_token=token,
            timeout=_CALL_TIMEOUT_SECONDS,
            max_retries=0,
            default_headers={"X-PostHog-Properties": properties},
            http_client=httpx.Client(trust_env=False),
        )
        output_format: JSONOutputFormatParam = {"type": "json_schema", "schema": dict(schema)}
        self.sent_request = True
        try:
            response = _create_with_effort_fallback(client, system_prompt, user_prompt, output_format)
        except Exception as exc:  # noqa: BLE001 - the cut is optional, so any API failure keeps every owner
            logger.warning("stamphog_reviewer_routing_call_failed", error_type=type(exc).__name__)
            return None
        finally:
            client.close()
        self.usage = CutUsage(input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens)
        if response.stop_reason != "end_turn":
            logger.info("stamphog_reviewer_routing_no_answer", stop_reason=response.stop_reason)
            return None
        text = "".join(block.text for block in response.content if block.type == "text")
        return _parse_answer(text)

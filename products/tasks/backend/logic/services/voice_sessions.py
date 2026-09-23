from django.conf import settings

import requests
import structlog

from posthog.egress.openai_live.transport import create_live_session
from posthog.egress.transport.transport import EgressBudgetExhausted

logger = structlog.get_logger(__name__)

VOICE_INSTRUCTIONS = (
    "You are the voice interface for an existing PostHog agent conversation. "
    "Keep replies short. Delegate every request for work, facts, or changes to the client backend. "
    "The backend has the full conversation and all tools. Never claim an action succeeded without its result. "
    "The user must answer permission requests in the app. Do not grant or infer approvals. "
    "Tell the user when the backend needs input. Ending this call does not stop their task."
)


class VoiceSessionUnavailable(Exception):
    pass


class VoiceSessionService:
    def create(self, sdp: str, context: str) -> dict[str, str]:
        if not settings.OPENAI_LIVE_API_KEY:
            raise VoiceSessionUnavailable
        try:
            response = create_live_session(
                settings.OPENAI_LIVE_API_KEY,
                {
                    "session": {
                        "model": "gpt-live-1",
                        "instructions": VOICE_INSTRUCTIONS,
                        "delegation": {"type": "client"},
                        "input": [
                            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": context}]}
                        ]
                        if context
                        else [],
                        "store": False,
                    },
                    "transport": {"type": "webrtc", "sdp": sdp},
                },
            )
            response.raise_for_status()
            data = response.json()
            answer = data["transport"]["sdp"]
            if not isinstance(answer, str) or not answer:
                raise ValueError("Missing voice answer")
            return {"sdp": answer}
        except (requests.RequestException, EgressBudgetExhausted, ValueError, KeyError, TypeError):
            logger.warning("desktop_voice_session_unavailable")
            raise VoiceSessionUnavailable from None

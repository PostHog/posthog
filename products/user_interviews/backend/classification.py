import re

from .models import UserInterviewClassification

# Vapi voice-interview transcripts are newline-delimited `AI:` / `User:` turns. Keep the
# speaker vocabulary in sync with frontend/parseTranscript.ts (TURN_SPLIT_RE) — both sides
# parse the same Vapi format independently.
_USER_TURN_RE = re.compile(
    r"(?:^|\n)\s*(?:User|Interviewee):\s+(.+?)(?=\n\s*(?:AI|Assistant|Interviewer|User|Interviewee):|$)",
    re.IGNORECASE | re.DOTALL,
)
_AI_TURN_RE = re.compile(r"(?:^|\n)\s*(?:AI|Assistant|Interviewer):\s+", re.IGNORECASE)


def _user_turns(transcript: str) -> list[str]:
    return [t.strip() for t in _USER_TURN_RE.findall(transcript) if t.strip()]


def derive_auto_classifications(transcript: str) -> list[str]:
    """Derive the mechanical classifications for a Vapi voice-interview transcript.

    Only `abandoned` is auto-derived — when the AI spoke but the interviewee never
    meaningfully did. `off-topic` needs human judgement and is never auto-set.

    Only the `AI:` / `User:` turn format (Vapi) is recognised. Transcripts in other formats
    (e.g. the audio-upload path's `#### Speaker N` headings) have no parseable turns, so we
    return no classifications rather than mislabel them `abandoned`.
    """
    if _user_turns(transcript):
        return []
    # No interviewee turns. Only call it `abandoned` when the AI clearly spoke (a real
    # voice interview the interviewee dropped); an unrecognised format gets left untagged.
    return [UserInterviewClassification.ABANDONED] if _AI_TURN_RE.search(transcript) else []

import hashlib
from collections import defaultdict

from pydantic import BaseModel, Field

from posthog.dataclasses import frozen

ALGORITHM_VERSION = 1
MAX_RECORDINGS = 200
MAX_VARIANTS = 50
MAX_STATES = 200
ANCHOR_PREFIXES = ("BODY:", "IMG:", "H1:", "H2:")


@frozen
class SignatureTokens:
    all: frozenset[str]
    anchors: frozenset[str]


class ReplayClick(BaseModel):
    x: float
    y: float
    target: str
    timestamp: float


class PageState(BaseModel):
    variant_id: str = ""
    window_id: int
    timestamp: float
    visit_id: str
    width: int = Field(gt=0, le=4000)
    height: int = Field(gt=0, le=20000)
    signature: list[str] = Field(max_length=500)
    clicks: list[ReplayClick] = Field(default_factory=list, max_length=1000)
    image: str = Field(default="", max_length=32)


class RecordingAnalysis(BaseModel):
    states: list[PageState] = Field(max_length=100)
    excluded_clicks: int = Field(default=0, ge=0)
    partial: bool = False


class VariantMember(BaseModel):
    session_id: str
    state: PageState


class PageVariant(BaseModel):
    id: str
    members: list[VariantMember]

    @staticmethod
    def member_id(member: VariantMember) -> str:
        return f"{member.session_id}:{member.state.window_id}:{int(member.state.timestamp)}"

    @staticmethod
    def tokens(state: PageState) -> SignatureTokens:
        signature = frozenset(state.signature)
        return SignatureTokens(
            all=signature, anchors=frozenset(token for token in signature if token.startswith(ANCHOR_PREFIXES))
        )

    @staticmethod
    def token_similarity(
        left: PageState,
        left_tokens: SignatureTokens,
        right: PageState,
        right_tokens: SignatureTokens,
    ) -> float:
        if left.width != right.width or abs(left.height - right.height) > 32:
            return 0
        if left_tokens.anchors != right_tokens.anchors:
            return 0
        a, b = left_tokens.all, right_tokens.all
        return len(a & b) / len(a | b) if a and b else 0

    def representative(self, selected: str | None = None) -> VariantMember:
        for member in self.members:
            if self.member_id(member) == selected:
                return member
        candidates = [
            (member, self.tokens(member.state)) for member in self.members[:: max(1, len(self.members) // 20)][:20]
        ]
        return max(
            candidates,
            key=lambda candidate: sum(
                self.token_similarity(candidate[0].state, candidate[1], other.state, tokens)
                for other, tokens in candidates
            ),
        )[0]

    def visit_keys(self) -> set[str]:
        return {f"{member.session_id}:{member.state.visit_id}" for member in self.members}

    def excluded_clicks(self, representative: VariantMember) -> int:
        signature = set(representative.state.signature)
        return sum(click.target not in signature for member in self.members for click in member.state.clicks)

    def summary(self, selected: str | None = None, representative: VariantMember | None = None) -> dict[str, object]:
        representative = representative or self.representative(selected)
        signature = set(representative.state.signature)
        timestamps = [member.state.timestamp for member in self.members]
        coordinates: dict[tuple[int, int], int] = defaultdict(int)
        for member in self.members:
            for click in member.state.clicks:
                if click.target in signature:
                    coordinates[(round(click.x / 8) * 8, round(click.y / 8) * 8)] += 1
        return {
            "id": self.id,
            "session_id": representative.session_id,
            "window_id": representative.state.window_id,
            "timestamp": representative.state.timestamp,
            "representative_replaced": bool(selected and selected != self.member_id(representative)),
            "width": representative.state.width,
            "height": representative.state.height,
            "recordings": len({member.session_id for member in self.members}),
            "visits": len(self.visit_keys()),
            "first_seen": min(timestamps),
            "last_seen": max(timestamps),
            "clicks": [{"x": x, "y": y, "count": count} for (x, y), count in coordinates.items()],
            "alternatives": [
                {"id": self.member_id(member), "session_id": member.session_id, "timestamp": member.state.timestamp}
                for member in [
                    representative,
                    *[m for m in self.members if self.member_id(m) != self.member_id(representative)][:19],
                ]
            ],
        }


def group_page_states(recordings: dict[str, RecordingAnalysis]) -> list[PageVariant]:
    variants: list[tuple[PageVariant, SignatureTokens]] = []
    states = sorted(
        ((session_id, state) for session_id, recording in recordings.items() for state in recording.states),
        key=lambda item: (not item[1].variant_id, item[0], item[1].timestamp, item[1].window_id),
    )
    for session_id, state in states:
        if not state.signature or not state.image:
            continue
        member = VariantMember(session_id=session_id, state=state)
        tokens = None if state.variant_id else PageVariant.tokens(state)
        matched = next(
            (
                variant
                for variant, head in variants
                if (
                    variant.id == state.variant_id
                    if tokens is None
                    else PageVariant.token_similarity(variant.members[0].state, head, state, tokens) >= 0.95
                )
            ),
            None,
        )
        if matched:
            matched.members.append(member)
        else:
            identity = f"{ALGORITHM_VERSION}:{state.width}:{state.height}:" + ":".join(sorted(state.signature))
            variant = PageVariant(
                id=state.variant_id or hashlib.sha256(identity.encode()).hexdigest()[:24], members=[member]
            )
            variants.append((variant, tokens or PageVariant.tokens(state)))
    return sorted((variant for variant, _ in variants), key=lambda variant: (-len(variant.visit_keys()), variant.id))

"""Exported enums for social_signals."""

from enum import StrEnum


class SourceKind(StrEnum):
    """Where a Mention came from. Each value maps to a WebhookAdapter / poller."""

    OCTOLENS = "octolens"
    MANUAL = "manual"


class Platform(StrEnum):
    """Social platform the mention was posted on. Not exhaustive; use OTHER as escape hatch."""

    X = "x"
    LINKEDIN = "linkedin"
    REDDIT = "reddit"
    HACKER_NEWS = "hacker_news"
    GITHUB = "github"
    YOUTUBE = "youtube"
    BLUESKY = "bluesky"
    MASTODON = "mastodon"
    OTHER = "other"


class MentionType(StrEnum):
    """Kind of social object the mention is."""

    POST = "post"
    COMMENT = "comment"
    REPLY = "reply"
    ARTICLE = "article"
    ISSUE = "issue"
    OTHER = "other"


class ProcessingStatus(StrEnum):
    """Lifecycle of a Mention through the analyzer pipeline."""

    PENDING = "pending"
    ANALYZING = "analyzing"
    DONE = "done"
    FAILED = "failed"


class AnalyzerKind(StrEnum):
    """Known analyzer kinds. The registry adds new entries here as analyzers ship."""

    CLASSIFY_AND_SENTIMENT = "classify_and_sentiment"


class AnalysisStatus(StrEnum):
    """Per-analyzer-per-mention status."""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Sentiment(StrEnum):
    """Sentiment label produced by the classify_and_sentiment analyzer."""

    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class MentionCategory(StrEnum):
    """Coarse category produced by the classify_and_sentiment analyzer."""

    BUG = "bug"
    FEATURE_REQUEST = "feature_request"
    PRAISE = "praise"
    QUESTION = "question"
    COMPLAINT = "complaint"
    COMPARISON = "comparison"
    OTHER = "other"

from posthog.dataclasses import frozen


@frozen
class PullRequestHead:
    repository: str
    pr_number: int
    head_sha: str


class DocsFreshnessCheckError(Exception):
    pass


class MergeRefBehindHead(DocsFreshnessCheckError):
    pass


class MergeRefMissing(DocsFreshnessCheckError):
    pass

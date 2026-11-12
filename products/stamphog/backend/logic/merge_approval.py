"""Which review run approves one head of a pull request.

The merge capture (``_record_merged_pull_request``) and the routing run list both ask this, so the
rule for "stamphog approved this head" lives in one place.
"""

from __future__ import annotations

from django.db.models import OuterRef, Q, QuerySet, Value
from django.db.models.functions import JSONArray

from ..facade.enums import ReviewVerdict
from ..models import ReviewRun
from .approval_retention import RETAINED_HEADS_KEY

# A dismissed approval is no longer stamphog's verdict: a same-head re-review may have voided it
# and then refused.
_STANDING_APPROVAL = Q(verdict=ReviewVerdict.APPROVED, approval_dismissed_at__isnull=True)


def approved_at_head(head_sha: str | OuterRef) -> Q:
    """A standing approval posted at exactly this head."""
    return _STANDING_APPROVAL & Q(head_sha=head_sha)


def retained_at_head(head_sha: str | OuterRef) -> Q:
    """A standing approval that retention carried to this head.

    The diff at a retained head is byte-identical to the approved diff (see
    ``logic/approval_retention.py``), so the approval covers it although it was never posted there.
    """
    head = Value(head_sha) if isinstance(head_sha, str) else head_sha
    return _STANDING_APPROVAL & Q(**{f"output__{RETAINED_HEADS_KEY}__contains": JSONArray(head)})


def approving_run_at_head(runs: QuerySet[ReviewRun], head_sha: str) -> ReviewRun | None:
    """The newest run in ``runs`` that approves ``head_sha``, preferring one posted at that head."""
    posted = runs.filter(approved_at_head(head_sha)).order_by("-created_at").first()
    if posted is not None:
        return posted
    return runs.filter(retained_at_head(head_sha)).order_by("-created_at").first()

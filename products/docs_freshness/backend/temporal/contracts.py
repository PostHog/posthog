from posthog.dataclasses import frozen

from products.docs_freshness.backend.facade.contracts import PullRequestHead
from products.docs_freshness.backend.logic.impact_check import ImpactVerdict, VerdictName


@frozen
class RecordVerdictInput:
    head: PullRequestHead
    verdict_name: VerdictName
    verdict: ImpactVerdict

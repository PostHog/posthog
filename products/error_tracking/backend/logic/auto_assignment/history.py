from collections import Counter

from products.error_tracking.backend.logic.auto_assignment.base import Candidate, HistoryEvidence, Processor
from products.error_tracking.backend.logic.auto_assignment.evidence import IssueEvidence
from products.error_tracking.backend.logic.auto_assignment.gate import AutoAssignmentConfig


class HistoryVote(Processor):
    name = "history"

    def threshold(self, config: AutoAssignmentConfig) -> float:
        return config.history.min_confidence

    def propose(self, evidence: IssueEvidence, config: AutoAssignmentConfig) -> Candidate | None:
        lookup = evidence.similar_assigned_issues
        if lookup is None:
            return None
        voters = [
            issue for issue in lookup.issues[: config.history.top_k] if issue.distance <= config.history.max_distance
        ]
        if not voters:
            return None
        votes = Counter(issue.assignee for issue in voters)
        top_votes = max(votes.values())
        # On a tie the assignee of the nearest issue wins, because voters are nearest first.
        winner = next(issue.assignee for issue in voters if votes[issue.assignee] == top_votes)
        supporting = [issue for issue in voters if issue.assignee == winner]
        # Divide by top_k, not by the voter count, so that one close match out of three is weak evidence.
        return Candidate(
            assignee=winner,
            confidence=top_votes / config.history.top_k,
            source=self.name,
            reason=f"Assigned on {top_votes} of the {config.history.top_k} most similar past issues",
            evidence=HistoryEvidence(
                similar_issue_ids=tuple(issue.issue_id for issue in supporting),
                nearest_distance=supporting[0].distance,
            ),
        )

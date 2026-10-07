from collections.abc import Mapping

from ...facade.enums import WarehouseSuggestionKind
from .base import Candidate, CandidateContext, CandidateResult, Rejection
from .certify import CertifyCandidate
from .deprecate import DeprecateCandidate
from .materialize import MaterializeCandidate

CANDIDATES: Mapping[WarehouseSuggestionKind, Candidate] = {
    WarehouseSuggestionKind.CERTIFY: CertifyCandidate(),
    WarehouseSuggestionKind.DEPRECATE: DeprecateCandidate(),
    WarehouseSuggestionKind.MATERIALIZE: MaterializeCandidate(),
}


def evaluate_candidates(context: CandidateContext) -> dict[WarehouseSuggestionKind, CandidateResult]:
    return {kind: candidate.evaluate(context) for kind, candidate in CANDIDATES.items()}


__all__ = ["CANDIDATES", "CandidateContext", "CandidateResult", "Rejection", "evaluate_candidates"]

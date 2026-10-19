from collections.abc import Mapping

from ...facade.enums import WarehouseSuggestionKind
from .base import Candidate, CandidateContext, CandidateResult
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

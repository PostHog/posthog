from collections.abc import Mapping

from ...facade.enums import WarehouseSuggestionKind
from .base import Candidate, CandidateContext, CandidateResult
from .certify import CertifyCandidate
from .dematerialize import DematerializeCandidate
from .deprecate import DeprecateCandidate
from .materialize import MaterializeCandidate

CANDIDATES: Mapping[WarehouseSuggestionKind, Candidate] = {
    WarehouseSuggestionKind.CERTIFY: CertifyCandidate(),
    WarehouseSuggestionKind.DEPRECATE: DeprecateCandidate(),
    WarehouseSuggestionKind.MATERIALIZE: MaterializeCandidate(),
    WarehouseSuggestionKind.DEMATERIALIZE: DematerializeCandidate(),
}


def evaluate_candidates(context: CandidateContext) -> dict[WarehouseSuggestionKind, CandidateResult]:
    return {kind: candidate.evaluate(context) for kind, candidate in CANDIDATES.items()}

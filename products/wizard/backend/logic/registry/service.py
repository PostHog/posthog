import logging

import posthoganalytics
from posthoganalytics.request import APIError, RequestsConnectionError, RequestsTimeout

from products.wizard.backend.facade.contracts import WizardProgram
from products.wizard.backend.facade.errors import WizardProgramNotAvailableError
from products.wizard.backend.logic.registry.config import FALLBACK_REGISTRY, REGISTRY_FEATURE_FLAG
from products.wizard.backend.logic.registry.parser import parse_registry_payload
from products.wizard.backend.metrics import report_registry_fallback

logger = logging.getLogger(__name__)


def get_registry(*, distinct_id: str, organization_id: str) -> tuple[WizardProgram, ...]:
    try:
        payload = posthoganalytics.get_feature_flag_payload(
            REGISTRY_FEATURE_FLAG,
            distinct_id=distinct_id,
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    except (APIError, RequestsConnectionError, RequestsTimeout):
        logger.warning("wizard_registry_fallback", extra={"reason": "request_failed"}, exc_info=True)
        report_registry_fallback("request_failed")
        return FALLBACK_REGISTRY.programs

    try:
        registry = parse_registry_payload(payload)
    except ValueError:
        logger.warning("wizard_registry_fallback", extra={"reason": "invalid_payload"}, exc_info=True)
        report_registry_fallback("invalid_payload")
        return FALLBACK_REGISTRY.programs
    return registry.programs


def get_program(*, program_id: str, distinct_id: str, organization_id: str) -> WizardProgram:
    programs = get_registry(distinct_id=distinct_id, organization_id=organization_id)
    program = next((program for program in programs if program.id == program_id), None)
    if program is None:
        raise WizardProgramNotAvailableError
    return program

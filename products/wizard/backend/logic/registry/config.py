from products.wizard.backend.facade.config import DEFAULT_WIZARD_VERSION
from products.wizard.backend.facade.contracts import WizardProgram, WizardRegistry
from products.wizard.backend.facade.enums import WizardRunEnvironment

REGISTRY_FEATURE_FLAG = "wizard-program-registry"

POSTHOG_INTEGRATION_PROGRAM = WizardProgram(
    id="posthog-integration",
    name="PostHog integration",
    description="Set up PostHog SDK integration",
    wizard_version=DEFAULT_WIZARD_VERSION,
    command=(),
    tags=(),
    required_programs=(),
    supported_environments=(WizardRunEnvironment.LOCAL, WizardRunEnvironment.CLOUD),
)

FALLBACK_REGISTRY = WizardRegistry(programs=(POSTHOG_INTEGRATION_PROGRAM,))

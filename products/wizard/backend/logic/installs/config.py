from datetime import timedelta

from products.wizard.backend.logic.registry.config import POSTHOG_INTEGRATION_PROGRAM

INSTALL_PROGRAM_ID = POSTHOG_INTEGRATION_PROGRAM.id

TOKEN_DAILY_RUN_LIMIT = 15
TOKEN_DAILY_RUN_COUNTER_TTL = timedelta(days=2)

LOCAL_WIZARD_COMMAND = "npx -y @posthog/wizard@latest"

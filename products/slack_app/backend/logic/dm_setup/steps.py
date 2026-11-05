from products.slack_app.backend.logic.dm_setup.link_account_step import LINK_ACCOUNT_STEP
from products.slack_app.backend.logic.dm_setup.model_step import MODEL_STEP
from products.slack_app.backend.logic.dm_setup.replies_step import REPLIES_IN_THREADS_STEP
from products.slack_app.backend.logic.dm_setup.step import DmSetupStep

# In display order. The account link comes first, because the steps after it save settings for the linked user.
DM_SETUP_STEPS: tuple[DmSetupStep, ...] = (LINK_ACCOUNT_STEP, MODEL_STEP, REPLIES_IN_THREADS_STEP)

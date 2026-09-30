from enum import StrEnum


class EmailTrackingConsentMode(StrEnum):
    # No consent enforcement: tracking follows the email step's own setting only.
    OFF = "off"
    # Track by default; suppress tracking for recipients who have opted out.
    OPT_OUT = "opt_out"
    # Do not track unless the recipient has explicitly opted in.
    OPT_IN = "opt_in"


# The labels Django's TextChoices derived from the member names, so the model field and the API
# schema keep the same choices.
EMAIL_TRACKING_CONSENT_MODE_CHOICES = [
    (mode.value, mode.name.replace("_", " ").title()) for mode in EmailTrackingConsentMode
]

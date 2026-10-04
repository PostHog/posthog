import re

from django.core import validators
from django.utils.deconstruct import deconstructible


# The product is retired. Historical migrations still import this validator, so it stays.
@deconstructible
class EmailWithDisplayNameValidator:
    # In "Michael (some guy) <michael@x.com>" display_name_regex's group 1 matches "Michael"
    # (round brackets are comments according to RFC #822, content in there is ignored), and group 2 matches "michael@x.com"
    display_name_regex = r"([^(]+) <(.+)>$"

    def __call__(self, value: str) -> None:
        display_name_match = re.match(self.display_name_regex, value)
        if display_name_match:
            value = display_name_match.group(2).strip()
        return validators.validate_email(value)

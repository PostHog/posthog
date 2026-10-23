"""The addresses a code send takes, held to what the email pipeline accepts."""

import re
from typing import Any

from rest_framework import serializers

from products.messaging.backend.facade.transactional_email import SENDER_ADDRESS_MAX_LENGTH

# A bare address with none of the characters that would let one entry of a comma-separated list name a second one.
PLAIN_ADDRESS = re.compile(r"[^\s@\"<>,;:()\[\]\\]+@[^\s@\"<>,;:()\[\]\\]+\.[^\s@\"<>,;:()\[\]\\]+")


def plain_address(value: str) -> None:
    if len(value) > SENDER_ADDRESS_MAX_LENGTH or not PLAIN_ADDRESS.fullmatch(value):
        raise serializers.ValidationError(f"`{value}` is not a bare address. Send it as `jane@example.com`.")


class PlainAddressField(serializers.EmailField):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.validators.append(plain_address)

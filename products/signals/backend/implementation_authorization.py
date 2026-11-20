from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator


class ImplementationAuthorization(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    mode: Literal["reviewer", "user"]
    user_id: int | None = None

    @model_validator(mode="after")
    def validate_principal(self) -> "ImplementationAuthorization":
        if (self.mode == "user") != (self.user_id is not None):
            raise ValueError("User authorization requires an authenticated user")
        return self

    @classmethod
    def from_stored(cls, value: object) -> "ImplementationAuthorization | None":
        try:
            return cls.model_validate(value)
        except ValidationError:
            return None

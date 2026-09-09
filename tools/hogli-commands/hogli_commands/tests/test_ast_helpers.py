from __future__ import annotations

from pathlib import Path

import pytest

from hogli_commands.product.ast_helpers import get_frozen_dataclass_names, get_model_names

MODELS_SOURCE = """
from django.db import models
from posthog.models.scoping import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class Channel(TeamScopedRootMixin):
    class ChannelType(models.TextChoices):
        PUBLIC = "public", "Public"

    name = models.TextField()


class SyncConfig(CreatedMetaFields, UpdatedMetaFields):
    team_id = models.BigIntegerField()


class Widget(UUIDModel):
    pass


class AbstractBase(TeamScopedRootMixin, UUIDModel):
    class Meta:
        abstract = True


class Flavor(models.TextChoices):
    VANILLA = "vanilla", "Vanilla"


class WidgetManager(models.Manager):
    pass


class PlainHelper:
    pass
"""

NO_DJANGO_SOURCE = """
from pydantic import BaseModel


class Payload(BaseModel):
    name: str
"""


class TestGetModelNames:
    @pytest.mark.parametrize(
        "name, expected",
        [
            ("Channel", True),  # indirect base: TeamScopedRootMixin, no 'Model' suffix
            ("SyncConfig", True),  # meta-fields mixins only
            ("Widget", True),  # classic 'Model'-suffix base
            ("AbstractBase", False),  # Meta.abstract = True never comes out of the registry
            ("Flavor", False),  # module-level choices class
            ("ChannelType", False),  # nested choices class
            ("WidgetManager", False),  # manager helper
            ("PlainHelper", False),  # no bases
        ],
    )
    def test_classification(self, tmp_path: Path, name: str, expected: bool) -> None:
        backend = tmp_path / "backend"
        backend.mkdir()
        (backend / "models.py").write_text(MODELS_SOURCE)
        assert (name in get_model_names(backend)) is expected

    def test_ignores_files_without_django_imports(self, tmp_path: Path) -> None:
        backend = tmp_path / "backend"
        backend.mkdir()
        (backend / "models.py").write_text(NO_DJANGO_SOURCE)
        assert get_model_names(backend) == []


FROZEN_DATACLASS_SOURCE = """
import posthog.dataclasses
from dataclasses import dataclass

from posthog.dataclasses import frozen


@frozen
class HouseDefault:
    name: str


@frozen(slots=True)
class HouseWithOptions:
    name: str


@frozen(frozen=False)
class HouseOptedOut:
    name: str


@posthog.dataclasses.frozen
class HouseQualified:
    name: str


@dataclass(frozen=True)
class StdlibFrozen:
    name: str


@dataclass
class StdlibMutable:
    name: str
"""


class TestGetFrozenDataclassNames:
    @pytest.mark.parametrize(
        "name, expected",
        [
            ("HouseDefault", True),  # @frozen is frozen unless it says otherwise
            ("HouseWithOptions", True),  # an unrelated keyword does not unfreeze it
            ("HouseOptedOut", False),  # frozen=False is the opt-out
            ("HouseQualified", True),  # module prefix stripped before matching
            ("StdlibFrozen", True),
            ("StdlibMutable", False),  # stdlib is mutable unless frozen=True
        ],
    )
    def test_classification(self, tmp_path: Path, name: str, expected: bool) -> None:
        source = tmp_path / "contracts.py"
        source.write_text(FROZEN_DATACLASS_SOURCE)
        assert (name in get_frozen_dataclass_names(source)) is expected

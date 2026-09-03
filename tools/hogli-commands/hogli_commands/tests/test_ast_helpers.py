from __future__ import annotations

from pathlib import Path

import pytest

from hogli_commands.product.ast_helpers import get_model_names

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

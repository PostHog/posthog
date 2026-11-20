from __future__ import annotations

from pathlib import Path

import pytest

from hogli_commands.product.ast_helpers import get_model_names

MODELS_SOURCE = """
from django.db import models
from pydantic import BaseModel
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


class Derived(AbstractBase):
    pass


class Payload(BaseModel):
    name: str


class Flavor(models.TextChoices):
    VANILLA = "vanilla", "Vanilla"


class WidgetManager(models.Manager):
    pass


class PlainHelper:
    pass
"""


class TestGetModelNames:
    @pytest.mark.parametrize(
        "name, expected",
        [
            ("Channel", True),  # indirect base: TeamScopedRootMixin, no 'Model' suffix
            ("SyncConfig", True),  # meta-fields mixins only
            ("Widget", True),  # classic 'Model'-suffix base
            ("AbstractBase", False),  # Meta.abstract = True never comes out of the registry
            ("Derived", True),  # ...but it is still how its subclass reaches a Django base
            ("Payload", False),  # a pydantic model in a models file validates a field, not a table
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

    def test_a_proxy_model_is_reached_through_its_concrete_model(self, tmp_path: Path) -> None:
        # A proxy model sits in another module and subclasses its concrete model, so only a
        # resolution that reaches across the model modules finds it. Dropping it lets a facade hand
        # the class out with no finding.
        models_dir = tmp_path / "backend" / "models"
        models_dir.mkdir(parents=True)
        (models_dir / "widgets.py").write_text(MODELS_SOURCE)
        (models_dir / "web_widget.py").write_text(
            "from posthog.models.utils import RootTeamManager\n\n"
            "from .widgets import Widget\n\n\n"
            "class WebWidgetManager(RootTeamManager):\n    pass\n\n\n"
            "class WebWidget(Widget):\n    class Meta:\n        proxy = True\n"
        )
        names = get_model_names(tmp_path / "backend")
        assert "WebWidget" in names
        assert "WebWidgetManager" not in names

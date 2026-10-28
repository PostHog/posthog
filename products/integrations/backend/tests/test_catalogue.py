import shutil
import textwrap
from pathlib import Path
from typing import Any

import pytest

from django.test import SimpleTestCase

import mypy.api
from hogli_commands.projections import PROJECTIONS, OutputFormatter, ProjectionRunner
from parameterized import parameterized

from posthog.models.integration import Integration

from products.integrations.backend.facade.api import IntegrationManager
from products.integrations.backend.facade.api_accessors import AuthAccessor, IntegrationReader
from products.integrations.backend.facade.catalogue import KINDS
from products.integrations.backend.facade.contracts import UnsupportedIntegrationFilter
from products.integrations.backend.facade.enums import AuthType
from products.integrations.backend.facade.kinds_generated import IntegrationKind

REPO_ROOT = Path(__file__).resolve().parents[4]
BACKEND = REPO_ROOT / "products/integrations/backend"


class TestCatalogue(SimpleTestCase):
    def test_kinds_match_the_model_choices(self) -> None:
        assert set(KINDS) == set(Integration.IntegrationKind.values) == {kind.value for kind in IntegrationKind}

    def test_generated_file_is_in_sync_with_the_catalogue(self) -> None:
        [projection] = [projection for projection in PROJECTIONS if projection.name == "integration-kinds"]
        runner = ProjectionRunner(REPO_ROOT, [projection], OutputFormatter(REPO_ROOT))

        assert runner.stale(projection) == [], "Run `hogli build:projections --only integration-kinds`."

    @parameterized.expand([(kind,) for kind in sorted(KINDS)])
    def test_each_kind_has_exactly_its_supported_auth_types(self, kind: str) -> None:
        accessor = getattr(IntegrationManager, kind.replace("-", "_"))
        present = {auth_type for auth_type in AuthType if hasattr(accessor, auth_type.value)}

        assert present == KINDS[kind].supported
        assert all(type(getattr(accessor, auth_type.value)) is AuthAccessor for auth_type in present)
        assert type(accessor.any) is IntegrationReader

    @parameterized.expand(
        [
            ("create",),
            ("upsert",),
            ("update",),
            ("update_atomically",),
            ("update_by_external_id",),
            ("acreate",),
            ("aupdate",),
        ]
    )
    def test_any_readers_have_no_writes(self, method: str) -> None:
        assert not hasattr(IntegrationManager.any, method)
        assert not hasattr(IntegrationManager.stripe.any, method)
        assert hasattr(IntegrationManager.stripe.token, method)

    @parameterized.expand(
        [
            ("lookup_in_key", {"account__name": "a"}),
            ("auth_type_key", {"auth_type": "token"}),
            ("marker_key", {"warehouse_source_type": "Stripe"}),
            ("empty_key", {"": "a"}),
            ("key_with_a_dash", {"a-b": "a"}),
            ("key_starts_with_a_digit", {"1a": "a"}),
            ("dict_value", {"account": {"name": "a"}}),
            ("list_value", {"ids": [1, 2]}),
            ("tuple_value", {"ids": (1,)}),
        ]
    )
    def test_find_rejects_unsupported_filters(self, _name: str, where: dict[str, Any]) -> None:
        with self.assertRaises(UnsupportedIntegrationFilter):
            IntegrationManager.github.oauth.find(1, where=where)


# The SDK modules are copied into an empty directory, so mypy reads them without the Django plugin
# and without following imports into the rest of the repo. Imports it cannot find become `Any`.
SDK_FILES = (
    "facade/api.py",
    "facade/api_accessors.py",
    "facade/catalogue.py",
    "facade/contracts.py",
    "facade/enums.py",
    "facade/kinds_generated.py",
    "logic/source_kinds.py",
    "logic/usages.py",
)

SNIPPET = """
from products.integrations.backend.facade.api import IntegrationManager

IntegrationManager.github.oauth.create(1, external_id="x", config={})
IntegrationManager.github.token.upsert(1, "x", config={})
IntegrationManager.source("ably").token.create(1, external_id="x", config={})
IntegrationManager.stripe.any.get(1, 2)
IntegrationManager.any.list(1)
IntegrationManager.stripe.any.create(1, external_id="x", config={})
IntegrationManager.github.credentials
IntegrationManager.any.update(1, 2, errors="")
IntegrationManager.postgresql.oauth
IntegrationManager.stripe.any.upsert(1, "x", config={})
"""


@pytest.mark.timeout(300)
def test_mypy_rejects_unsupported_auth_types_and_writes_through_any(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # mypy also searches the working directory, which would pull in the whole repo.
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "src"
    for relative in SDK_FILES:
        target = root / "products/integrations/backend" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(BACKEND / relative, target)
    for package in ("products", "products/integrations", "products/integrations/backend"):
        (root / package / "__init__.py").touch()
    for package in ("facade", "logic"):
        (root / "products/integrations/backend" / package / "__init__.py").touch()
    (root / "snippet.py").write_text(textwrap.dedent(SNIPPET))
    (tmp_path / "mypy.ini").write_text("[mypy]\n")

    stdout, stderr, _ = mypy.api.run(
        [
            "--config-file",
            str(tmp_path / "mypy.ini"),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--no-site-packages",
            "--ignore-missing-imports",
            "--no-error-summary",
            "--hide-error-context",
            str(root / "snippet.py"),
        ]
    )

    errors = sorted(
        (int(line.split(":")[1]), line.split(": error: ")[1].split("  [")[0])
        for line in stdout.splitlines()
        if "snippet.py" in line and ": error: " in line
    )
    assert errors == [
        (9, '"IntegrationReader" has no attribute "create"'),
        (10, '"GithubKind" has no attribute "credentials"'),
        (11, '"IntegrationReader" has no attribute "update"'),
        (12, '"PostgresqlKind" has no attribute "oauth"'),
        (13, '"IntegrationReader" has no attribute "upsert"'),
    ], stdout + stderr

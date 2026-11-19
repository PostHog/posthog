from __future__ import annotations

import json
from pathlib import Path

import pytest

from hogli_commands.product.checks import CheckContext, WatchedChannelsCheck
from hogli_commands.product.isolation import compute_isolation_status
from hogli_commands.product.watched_channels import (
    UNRESOLVED_SUBMODULE_PREFIX,
    app_setup_modules,
    discovered_modules,
    foreign_receiver_modules,
    hook_callback_modules,
    outside_named_modules,
    settings_named_modules,
)

_SIGNAL_IMPORTS = "from django.db.models.signals import post_save\nfrom django.dispatch import receiver\n\n"


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def _write_products(repo_root: Path, mine: dict[str, str]) -> Path:
    for name in ("mine", "other"):
        _write(
            repo_root / "products" / name / "backend",
            {"__init__.py": "", "apps.py": f'class Config:\n    label = "{name}"\n', "models.py": ""},
        )
    product_dir = repo_root / "products" / "mine"
    _write(product_dir / "backend", mine)
    return product_dir


class TestForeignReceivers:
    @pytest.mark.parametrize(
        "source, expected",
        [
            ('@receiver(post_save, sender="other.Thing")\ndef on_save(**kwargs): ...\n', {"backend/signals.py"}),
            (
                "from products.other.backend.models import Thing\n\n"
                "@receiver(post_save, sender=Thing)\ndef on_save(**kwargs): ...\n",
                {"backend/signals.py"},
            ),
            (
                "from posthog.models.user import User\n\n"
                "@receiver(post_save, sender=User)\ndef on_save(**kwargs): ...\n",
                {"backend/signals.py"},
            ),
            (
                "from django.conf import settings\n\n"
                "@receiver(post_save, sender=settings.AUTH_USER_MODEL)\ndef on_save(**kwargs): ...\n",
                {"backend/signals.py"},
            ),
            (
                'def on_save(**kwargs): ...\n\nfor model in ("mine.Widget",):\n'
                "    post_save.connect(on_save, sender=model)\n",
                {"backend/signals.py"},
            ),
            ('@receiver(post_save, sender="mine.Widget")\ndef on_save(**kwargs): ...\n', set()),
            (
                "from products.mine.backend.models import Widget\n\n"
                "@receiver(post_save, sender=Widget)\ndef on_save(**kwargs): ...\n",
                set(),
            ),
            (
                "from .models import Widget\n\n@receiver(post_save, sender=Widget)\ndef on_save(**kwargs): ...\n",
                set(),
            ),
        ],
        ids=[
            "string-sender-of-another-product",
            "imported-model-of-another-product",
            "imported-core-model",
            "auth-user-model-setting",
            "unresolvable-sender-fails-closed",
            "string-sender-of-own-product",
            "imported-own-model",
            "relative-import-of-own-model",
        ],
    )
    def test_sender_resolution(self, tmp_path: Path, source: str, expected: set[str]) -> None:
        product_dir = _write_products(tmp_path, {"signals.py": _SIGNAL_IMPORTS + source})
        assert {c.path for c in foreign_receiver_modules(product_dir)} == expected

    def test_connected_function_module_is_held_with_the_connecting_module(self, tmp_path: Path) -> None:
        product_dir = _write_products(
            tmp_path,
            {
                "handlers.py": "def on_save(**kwargs): ...\n",
                "apps.py": (
                    'class Config:\n    label = "mine"\n\n    def ready(self):\n'
                    "        from django.db.models.signals import post_save\n\n"
                    "        from . import handlers\n\n"
                    '        post_save.connect(handlers.on_save, sender="other.Thing")\n'
                ),
            },
        )
        assert {c.path for c in foreign_receiver_modules(product_dir)} == {"backend/apps.py", "backend/handlers.py"}

    @pytest.mark.parametrize(
        "hook_body, expected",
        [
            (
                "def connect_thing_saved(receiver, *, dispatch_uid):\n"
                "    post_save.connect(receiver, sender=Thing, dispatch_uid=dispatch_uid)\n",
                {"backend/receivers.py", "backend/handlers.py"},
            ),
            ("def connect_thing_saved(receiver, *, dispatch_uid):\n    return None\n", set()),
        ],
        ids=["hook-forwards-receiver-to-connect", "same-name-without-connect"],
    )
    def test_signal_hook_of_another_product(self, tmp_path: Path, hook_body: str, expected: set[str]) -> None:
        product_dir = _write_products(
            tmp_path,
            {
                "handlers.py": "def on_save(**kwargs): ...\n",
                "receivers.py": (
                    "from products.other.backend.facade.signals import connect_thing_saved\n\n"
                    "from .handlers import on_save\n\n"
                    "def connect():\n"
                    '    connect_thing_saved(on_save, dispatch_uid="mine")\n'
                ),
            },
        )
        _write(tmp_path / "products" / "other" / "backend" / "facade", {"signals.py": hook_body})
        assert {c.path for c in foreign_receiver_modules(product_dir)} == expected


class TestOutsideTestNames:
    @pytest.mark.parametrize(
        "test_path, source, expected",
        [
            (
                "posthog/api/test/test_thing.py",
                'patch("products.mine.backend.delivery.email.send_email")\n',
                {"backend/delivery/email.py"},
            ),
            (
                "products/other/backend/tests/test_thing.py",
                'MODULE = "products.mine.backend.delivery.email"\npatch(f"{MODULE}.send_email")\n',
                {"backend/delivery/email.py"},
            ),
            (
                "ee/tests/test_thing.py",
                'patch(\n    "products.mine.backend.delivery."\n    "email.send_email"\n)\n',
                {"backend/delivery/email.py"},
            ),
            (
                "products/mine/backend/tests/test_thing.py",
                'patch("products.mine.backend.delivery.email.send_email")\n',
                set(),
            ),
        ],
        ids=["patch-string", "module-constant-with-f-string", "implicit-concatenation", "test-inside-the-owner"],
    )
    def test_resolves_to_the_longest_module_file(
        self, tmp_path: Path, test_path: str, source: str, expected: set[str]
    ) -> None:
        _write_products(tmp_path, {"delivery/__init__.py": "", "delivery/email.py": ""})
        _write(tmp_path, {test_path: source})
        assert {c.path for c in outside_named_modules("mine", tmp_path)} == expected


class TestWatchedChannelsCheck:
    @pytest.mark.parametrize(
        "inputs, narrowed, unwatched",
        [
            (["backend/facade/**", "backend/apps.py", "backend/delivery/email.py"], True, []),
            (["backend/facade/**", "backend/apps.py", "backend/delivery/**"], False, []),
            (["backend/facade/**", "backend/apps.py"], True, ["backend/delivery/email.py"]),
            (
                ["backend/facade/**", "backend/apps.py", "backend/delivery/**", "!backend/delivery/email.py"],
                False,
                ["backend/delivery/email.py"],
            ),
        ],
        ids=["listed", "inside-a-listed-directory", "not-listed", "negated"],
    )
    def test_patched_module_must_be_in_the_inputs(
        self, tmp_path: Path, inputs: list[str], narrowed: bool, unwatched: list[str]
    ) -> None:
        product_dir = _write_products(tmp_path, {"facade/__init__.py": "", "delivery/email.py": ""})
        _write(
            product_dir,
            {
                "package.json": json.dumps({"scripts": {"backend:contract-check": "true"}}),
                "turbo.json": json.dumps({"tasks": {"backend:contract-check": {"inputs": inputs}}}),
            },
        )
        _write(tmp_path, {"posthog/test/test_thing.py": 'patch("products.mine.backend.delivery.email.send")\n'})
        backend_dir = product_dir / "backend"
        status = compute_isolation_status(
            "mine", product_dir, backend_dir, tach_content="", pyproject_text="", repo_root=tmp_path
        )
        ctx = CheckContext(
            name="mine",
            product_dir=product_dir,
            backend_dir=backend_dir,
            has_facade_contracts=False,
            structure={},
            detailed=False,
            _isolation=status,
        )

        result = WatchedChannelsCheck().run(ctx)

        assert status.has_narrowed_turbo is narrowed
        assert [issue.split(" ", 1)[0] for issue in result.issues] == unwatched


class TestDiscoveredByName:
    @pytest.mark.parametrize(
        "loader_source, expected",
        [
            ('load_product_modules("data_freshness")\n', {"backend/data_freshness.py"}),
            ('NAME = "data_freshness"\n\nload_product_modules(NAME)\n', {"backend/data_freshness.py"}),
            ('load_product_modules("facade.highlights")\n', {"backend/facade/highlights.py"}),
            ('load_product_modules("missing_here")\n', set()),
        ],
        ids=["literal-name", "module-constant", "dotted-name", "product-without-the-module"],
    )
    def test_names_resolve_to_product_modules(self, tmp_path: Path, loader_source: str, expected: set[str]) -> None:
        product_dir = _write_products(tmp_path, {"data_freshness.py": "", "facade/highlights.py": ""})
        _write(
            tmp_path / "posthog", {"loader.py": "from posthog.products import load_product_modules\n\n" + loader_source}
        )
        assert {c.path for c in discovered_modules(product_dir, tmp_path)} == expected

    def test_unreadable_name_fails_closed(self, tmp_path: Path) -> None:
        product_dir = _write_products(tmp_path, {})
        _write(tmp_path / "posthog", {"loader.py": "def load(name):\n    return load_product_modules(name)\n"})
        paths = [c.path for c in discovered_modules(product_dir, tmp_path)]
        assert len(paths) == 1 and paths[0].startswith(UNRESOLVED_SUBMODULE_PREFIX)


class TestAppSetup:
    def test_apps_module_and_its_runtime_imports(self, tmp_path: Path) -> None:
        product_dir = _write_products(
            tmp_path,
            {
                "receivers.py": "",
                "logic/__init__.py": "",
                "logic/projection.py": "def project(): ...\n",
                "typing_only.py": "",
                "apps.py": (
                    "from typing import TYPE_CHECKING\n\n"
                    "if TYPE_CHECKING:\n    from products.mine.backend.typing_only import Shape\n\n"
                    "class Config:\n    def ready(self):\n"
                    "        from products.mine.backend import receivers\n\n"
                    "        def resolver():\n"
                    "            from .logic.projection import project\n\n"
                    "            return project()\n"
                ),
            },
        )
        assert {c.path for c in app_setup_modules(product_dir)} == {
            "backend/apps.py",
            "backend/receivers.py",
            "backend/logic/projection.py",
        }


class TestHookCallbacks:
    @pytest.mark.parametrize(
        "hook_import, expected",
        [
            (
                "from products.other.backend.facade.hooks import register_describer",
                {"backend/registration.py", "backend/wording.py"},
            ),
            (
                "from posthog.admin.inline_registry import register_describer",
                {"backend/registration.py", "backend/wording.py"},
            ),
            ("from products.mine.backend.hooks import register_describer", set()),
            ("from structlog import register_describer", set()),
        ],
        ids=["hook-of-another-product", "hook-of-core", "own-hook", "third-party-function"],
    )
    def test_registration_and_registered_module(self, tmp_path: Path, hook_import: str, expected: set[str]) -> None:
        product_dir = _write_products(
            tmp_path,
            {
                "hooks.py": "",
                "wording.py": "def describe(): ...\n",
                "registration.py": f"{hook_import}\n\nfrom .wording import describe\n\nregister_describer(describe)\n",
            },
        )
        assert {c.path for c in hook_callback_modules(product_dir)} == expected


class TestSettingsNames:
    def test_middleware_path_resolves_to_its_module(self, tmp_path: Path) -> None:
        _write_products(tmp_path, {"middleware.py": "class SessionMiddleware: ...\n"})
        _write(
            tmp_path,
            {"posthog/settings/web.py": 'MIDDLEWARE = ["products.mine.backend.middleware.SessionMiddleware"]\n'},
        )
        assert {c.path for c in settings_named_modules("mine", tmp_path)} == {"backend/middleware.py"}

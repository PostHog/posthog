import json
import typing

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common import config


def test_empty_config():
    """Test `config.to_config` with an empty class."""

    @config.config
    class TestConfig(config.Config):
        pass

    cfg = TestConfig.from_dict({})
    assert cfg


def test_basic_to_config():
    """Test `config.to_config` with a basic class."""

    @config.config
    class TestConfig(config.Config):
        a: str
        b: int = 0
        c: str | None = None

    config_dict = {
        "a": "test",
        "c": "present",
    }

    cfg = TestConfig.from_dict(config_dict)

    assert cfg.a == "test"
    assert cfg.b == 0
    assert cfg.c == "present"


def test_basic_to_config_converters():
    """Test `config.to_config` can convert using converters."""

    @config.config
    class TestConfig(config.Config):
        a: int = config.value(converter=int)
        b: bool = config.value(converter=config.str_to_bool)
        c: bool = config.value(converter=config.str_to_bool)

    config_dict = {
        "a": "123",
        "b": "True",
        "c": "false",
    }

    cfg = TestConfig.from_dict(config_dict)

    assert cfg.a == 123
    assert cfg.b is True
    assert cfg.c is False


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("5432", 5432),
        (5432, 5432),
        # Numeric JSON values arrive as int/float, not str, and must not crash on `.strip()`.
        (5432.0, 5432),
        (158.220123243, 158),
    ],
)
def test_str_to_optional_int(value, expected):
    """`str_to_optional_int` must handle numeric (int/float) inputs, not only strings."""
    assert config.str_to_optional_int(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("5432", 5432),
        (5432.0, 5432),
    ],
)
def test_optional_int_converter_handles_numeric_via_from_dict(value, expected):
    """A NUMBER field fed through `Config.from_dict` must not crash and must coerce correctly."""

    @config.config
    class TestConfig(config.Config):
        port: int | None = config.value(converter=config.str_to_optional_int, default_factory=lambda: None)

    cfg = TestConfig.from_dict({"port": value})

    assert cfg.port == expected


# A representative Fernet token, as it appears when `job_inputs` decryption fails upstream and the
# raw ciphertext flows into config parsing. Not a real credential.
_UNDECRYPTED_TOKEN = (
    "gAAAAABqTJ0OKLTREfglaXr0DZrJ4eYT7GVcKeA0avLvEzY7k3ll0JuD8VpL--DGJ9Dbt9y3KwyAolvAXit1ceqyuOzwyjTqlg=="
)


@pytest.mark.parametrize(
    "config_dict",
    [
        # The reported crash: an int-converted `port` that never got decrypted would raise the
        # opaque `invalid literal for int() with base 10: 'gAAAAA...'`.
        {"host": "db.example.com", "port": _UNDECRYPTED_TOKEN},
        # A plain string field left encrypted must also fail here, not pass ciphertext downstream.
        {"host": _UNDECRYPTED_TOKEN, "port": "5432"},
    ],
)
def test_from_dict_raises_clear_error_on_undecrypted_secret(config_dict):
    """Still-encrypted job inputs must fail with a clear error that does not echo the token."""

    @config.config
    class TestConfig(config.Config):
        host: str
        port: int = config.value(converter=int)

    with pytest.raises(config.UndecryptedConfigError) as exc_info:
        TestConfig.from_dict(config_dict)

    assert _UNDECRYPTED_TOKEN not in str(exc_info.value)


def test_nested_to_config_with_flat_dict():
    """Test `config.to_config` with a nested set of classes.

    We test parsing a configuration from a flat dictionary while overriding
    prefixes used for each attribute.
    """

    @config.config
    class TestConfigA:
        a: str
        b: int = 0
        c: str | None = None

    @config.config
    class TestConfigB:
        a: TestConfigA = config.value(prefix="a")

    @config.config
    class TestConfigC(config.Config):
        a: TestConfigA = config.value(prefix="a")
        b: TestConfigB = config.value(prefix="b")
        d: bool = False

    config_dict = {
        "a_a": "test",
        "b_a_a": "test",
        "b_a_b": 1,
        "b_a_c": "something",
        "d": True,
    }

    cfg = TestConfigC.from_dict(config_dict)

    assert cfg.a.a == "test"
    assert cfg.a.b == 0
    assert cfg.a.c is None

    assert cfg.b.a.a == "test"
    assert cfg.b.a.b == 1
    assert cfg.b.a.c == "something"

    assert cfg.d is True


def test_nested_to_config_with_nested_dict():
    """Test `config.to_config` with a nested set of classes.

    We test parsing a configuration from a nested dictionary.
    """

    @config.config
    class TestConfigA:
        a: str
        b: int = 0
        c: str | None = None

    @config.config
    class TestConfigB:
        a: TestConfigA

    @config.config
    class TestConfigC(config.Config):
        a: TestConfigA
        b: TestConfigB
        d: bool = False

    config_dict = {
        "a": {
            "a": "test",
        },
        "b": {
            "a": {
                "a": "test",
                "b": 1,
                "c": "something",
            }
        },
        "d": True,
    }

    cfg = TestConfigC.from_dict(config_dict)

    assert cfg.a.a == "test"
    assert cfg.a.b == 0
    assert cfg.a.c is None

    assert cfg.b.a.a == "test"
    assert cfg.b.a.b == 1
    assert cfg.b.a.c == "something"

    assert cfg.d is True


@pytest.mark.parametrize("scalar_value", ["oauth", "api_key", None])
def test_nested_to_config_with_scalar_value_for_nested_key(scalar_value):
    """Test `config.to_config` when a nested-config field's key holds a scalar.

    Mirrors the auth-method payload shape where the selection field is sent flat
    (``{"auth_method": "oauth", ...}``) instead of nested. The scalar must not be
    treated as a nested mapping — doing so previously swallowed a ``TypeError`` and
    dropped the required field, crashing on instantiation. Parsing should instead
    fall through to flat resolution and pick up sibling flat fields.
    """

    @config.config
    class AuthMethod:
        selection: str = "api_key"
        secret_key: str | None = None

    @config.config
    class Source(config.Config):
        auth_method: AuthMethod
        account_id: str | None = None

    config_dict = {
        "auth_method": scalar_value,
        "secret_key": "rk_live_x",
        "account_id": "acct_xxx",
    }

    cfg = Source.from_dict(config_dict)

    assert isinstance(cfg.auth_method, AuthMethod)
    assert cfg.auth_method.secret_key == "rk_live_x"
    assert cfg.account_id == "acct_xxx"

    # validate_dict already accepts this shape, so from_dict must agree and not crash.
    is_valid, errors = Source.validate_dict(config_dict)
    assert is_valid, errors


def test_nested_to_config_with_flat_dict_default_prefix():
    """Test `config.to_config` with a nested set of classes.

    We are particularly interested in the mechanism to resolve default prefixes.
    Each class name should automatically resolve to a prefix that matches our
    flat dictionary.
    """

    @config.config
    class A:
        a: str
        b: int = 0
        c: str | None = None

    @config.config
    class B:
        a: A

    @config.config
    class C(config.Config):
        a: A
        b: B
        d: bool = False

    config_dict = {
        "a_a": "test",
        "b_a_a": "test",
        "b_a_b": 1,
        "b_a_c": "something",
        "d": True,
    }

    cfg = C.from_dict(config_dict)

    assert cfg.a.a == "test"
    assert cfg.a.b == 0
    assert cfg.a.c is None
    assert isinstance(cfg.a, A)

    assert cfg.b.a.a == "test"
    assert cfg.b.a.b == 1
    assert cfg.b.a.c == "something"
    assert isinstance(cfg.b, B)
    assert isinstance(cfg.b.a, A)

    assert cfg.d is True


def test_to_config_override_alias():
    """Test `config.to_config` with overriden lookup names.

    Lookup names in the flat dictionary can be specified when using
    `config.value`.
    """

    @config.config
    class TestConfig(config.Config):
        a: str = config.value(alias="not_a")
        b: int = config.value(alias="not_b")
        c: str | None = config.value(alias="not_c")

    config_dict = {
        "not_a": "test",
        "not_b": 10,
        "not_c": "seen",
        "c": "not-seen",
    }

    cfg = TestConfig.from_dict(config_dict)

    assert cfg.a == "test"
    assert cfg.b == 10
    assert cfg.c == "seen"


def test_to_config_override_alias_fallback():
    """Test `config.to_config` with overriden lookup names but
    fallback to the original name if the alias key os missing.

    Lookup names in the flat dictionary can be specified when using
    `config.value`.
    """

    @config.config
    class TestConfig(config.Config):
        a: str = config.value(alias="not_a")
        b: int = config.value(alias="not_b")
        c: str | None = config.value(alias="not_c")

    config_dict = {
        "a": "test",
        "b": 10,
        "not_c": "seen",
        "c": "not-seen",
    }

    cfg = TestConfig.from_dict(config_dict)

    assert cfg.a == "test"
    assert cfg.b == 10
    assert cfg.c == "seen"


def test_to_config_union_nested_configs():
    """Test `config.to_config` with a union of nested configs."""

    @config.config
    class A:
        a: str

    @config.config
    class B:
        b: int

    @config.config
    class C(config.Config):
        inner: A | B | int

    config_dict: dict[str, typing.Any] = {"inner": {"b": 1}}

    b_cfg = C.from_dict(config_dict)

    assert isinstance(b_cfg.inner, B)
    assert b_cfg.inner.b == 1

    config_dict = {"inner": {"a": "test"}}

    a_cfg = C.from_dict(config_dict)

    assert isinstance(a_cfg.inner, A)
    assert a_cfg.inner.a == "test"

    config_dict = {"inner": 2}

    a_cfg = C.from_dict(config_dict)

    assert isinstance(a_cfg.inner, int)
    assert a_cfg.inner == 2


def test_to_config_union_nested_configs_with_alias():
    """Test `config.to_config` with a union of nested configs using alias."""

    @config.config
    class A:
        a: str

    @config.config
    class B:
        b: int

    @config.config
    class C(config.Config):
        inner: A | B = config.value(alias="some")

    config_dict: dict[str, typing.Any] = {"some": {"b": 1}}

    b_cfg = C.from_dict(config_dict)

    assert isinstance(b_cfg.inner, B)
    assert b_cfg.inner.b == 1

    config_dict = {"some": {"a": "test"}}

    a_cfg = C.from_dict(config_dict)

    assert isinstance(a_cfg.inner, A)
    assert a_cfg.inner.a == "test"


@pytest.mark.parametrize(
    "config_dict,expected_selection,expected_integration_id,expected_secret_key,expected_account_id",
    [
        # Flat select payload: the option value as a scalar with the option's fields as
        # siblings. The scalar isn't mapped to `selection`, so it keeps its default and
        # the siblings are parsed flat.
        ({"auth_method": "oauth", "integration_id": 123, "account_id": "acct_x"}, "api_key", 123, None, "acct_x"),
        # Flat payload whose scalar sibling is a string field — it must survive the flat
        # fallback and land on the nested config (e.g. Stripe's `secret_key`).
        (
            {"auth_method": "api_key", "secret_key": "rk_live_x", "account_id": "acct_123"},
            "api_key",
            None,
            "rk_live_x",
            "acct_123",
        ),
        # Nested form keeps working unchanged.
        (
            {"auth_method": {"selection": "oauth", "integration_id": 456}, "account_id": "acct_y"},
            "oauth",
            456,
            None,
            "acct_y",
        ),
    ],
)
def test_to_config_scalar_under_nested_config_key(
    config_dict, expected_selection, expected_integration_id, expected_secret_key, expected_account_id
):
    """A scalar under a nested-config key must not crash `to_config`.

    A flat select payload (e.g. `auth_method: "oauth"` with the option's fields as
    siblings, instead of the nested `auth_method: {"selection": "oauth", ...}`) puts a
    scalar where a nested config dict is expected. `validate_config` already treats this
    as a flat structure (it guards with `isinstance(..., dict)`), so `to_config` must do
    the same and fall through to flat parsing instead of recursing into the scalar and
    raising an unhandled `TypeError`.
    """

    @config.config
    class AuthMethod:
        selection: str = "api_key"
        integration_id: int | None = config.value(converter=config.str_to_optional_int, default_factory=lambda: None)
        secret_key: str | None = None

    @config.config
    class SourceConfig(config.Config):
        auth_method: AuthMethod
        account_id: str | None = None

    # Validation accepts both shapes, so construction must not crash — the two functions
    # have to agree.
    is_valid, errors = SourceConfig.validate_dict(config_dict)
    assert is_valid is True
    assert errors == []

    cfg = SourceConfig.from_dict(config_dict)
    assert isinstance(cfg.auth_method, AuthMethod)
    assert cfg.auth_method.selection == expected_selection
    assert cfg.auth_method.integration_id == expected_integration_id
    assert cfg.auth_method.secret_key == expected_secret_key
    assert cfg.account_id == expected_account_id


@pytest.mark.parametrize("bad_input", ["not a mapping", '"scalar"', "[1, 2, 3]", b"bytes", 5, ["a", "b"], None])
def test_from_dict_with_non_mapping_raises_clear_error(bad_input):
    """A non-mapping input must raise an actionable error, not the opaque builtin `TypeError`.

    Stored config can come back as a non-mapping (e.g. a double-encoded string from an
    `EncryptedJSONField`). Indexing into it deep inside `to_config` raised
    `TypeError: string indices must be integers`, which is impossible to triage from the
    source alone. A string that decodes to a mapping is recovered, but any other shape
    (unparseable text, or JSON that decodes to a scalar/list) must be rejected up front with
    the config class name in the message.
    """

    @config.config
    class KeyFileConfig:
        project_id: str
        private_key: str

    @config.config
    class SourceConfig(config.Config):
        key_file: KeyFileConfig
        dataset_id: str

    with pytest.raises(TypeError, match="Cannot build 'SourceConfig'"):
        SourceConfig.from_dict(bad_input)


def test_from_dict_recovers_double_encoded_json_string():
    """A config stored as a JSON string (double-encoded by `EncryptedJSONField`) must be
    decoded back into a working config instead of crashing the sync with `Cannot build ...`.
    """

    @config.config
    class SourceConfig(config.Config):
        host: str
        port: int = 0

    config_dict = {"host": "example", "port": 5432}

    cfg = SourceConfig.from_dict(json.dumps(config_dict))

    assert cfg.host == "example"
    assert cfg.port == 5432


def test_to_config_optional_config_does_not_retain_unparseable_dict():
    # A present-but-unparseable mapping under an `Optional[Config]` field must not leak
    # through the `None` arm of the union as a raw dict. Doing so left a typed field
    # holding an untyped dict and crashed downstream with `'dict' object has no
    # attribute '<field>'`; the field must fall back to its default (None) instead.
    @config.config
    class AuthConfig:
        type: str  # required, so a payload that can't fill it makes the config arm fail

    @config.config
    class SourceConfig(config.Config):
        auth: AuthConfig | None = None

    cfg = SourceConfig.from_dict({"auth": {"unrecognized_key": "value"}})

    assert cfg.auth is None


@config.config
class _SecretFieldConfig(config.Config):
    password: str | None = None
    passphrase: str | None = None
    secret_key: str | None = None
    client_secret: str | None = None
    api_key: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    private_key: str | None = None
    client_certificate: str | None = None
    client_private_key: str | None = None
    server_client_root_ca: str | None = None
    connection_string: str | None = None
    manifest_json: str | None = None
    authorization_header: str | None = None
    signing_secret: str | None = None


@pytest.mark.parametrize(
    "field_name",
    [
        "password",
        "passphrase",
        "secret_key",
        "client_secret",
        "api_key",
        "access_token",
        "refresh_token",
        "private_key",
        "client_certificate",
        "client_private_key",
        "server_client_root_ca",
        "connection_string",
        "manifest_json",
        "authorization_header",
        "signing_secret",
    ],
)
def test_repr_redacts_secret_fields(field_name):
    cfg = _SecretFieldConfig()
    setattr(cfg, field_name, "super-secret-value")

    rendered = repr(cfg)
    assert "super-secret-value" not in rendered
    assert f"{field_name}='***'" in rendered


def test_repr_keeps_non_secret_fields_visible():
    @config.config
    class TestConfig(config.Config):
        host: str
        database: str
        user: str
        password: str

    cfg = TestConfig(host="db.example.com", database="prod", user="reader", password="hunter2")

    rendered = repr(cfg)
    assert "host='db.example.com'" in rendered
    assert "database='prod'" in rendered
    assert "user='reader'" in rendered
    # The credential is the only field redacted.
    assert "hunter2" not in rendered
    assert "password='***'" in rendered


def test_repr_shows_none_secret_as_none():
    @config.config
    class TestConfig(config.Config):
        password: str | None = None

    # An unset secret has nothing to leak, so it stays visible to aid debugging.
    assert "password=None" in repr(TestConfig())


def test_repr_redacts_nested_config_secrets():
    @config.config
    class AuthConfig:
        username: str
        password: str | None = None

    @config.config
    class TestConfig(config.Config):
        host: str
        auth: AuthConfig

    cfg = TestConfig(host="db.example.com", auth=AuthConfig(username="reader", password="hunter2"))

    rendered = repr(cfg)
    assert "hunter2" not in rendered
    assert "password='***'" in rendered
    assert "username='reader'" in rendered


def test_repr_redacts_real_postgres_source_config():
    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PostgresSourceConfig

    cfg = PostgresSourceConfig(
        host="fadevpn-11499.example.cloud",
        database="defaultdb",
        user="datawarehouse",
        password="hunter2",
        port=26257,
    )

    rendered = repr(cfg)
    assert "hunter2" not in rendered
    assert "password='***'" in rendered
    # Connection metadata stays visible for debugging.
    assert "host='fadevpn-11499.example.cloud'" in rendered


def test_repr_recurses_into_nested_config_with_secret_field_name():
    @config.config
    class KeyFileConfig:
        project_id: str
        client_email: str
        private_key: str

    @config.config
    class TestConfig(config.Config):
        # Field name contains "key" but holds a nested config, not a raw secret.
        key_file: KeyFileConfig

    cfg = TestConfig(
        key_file=KeyFileConfig(project_id="my-project", client_email="sa@example.com", private_key="-----BEGIN-----")
    )

    rendered = repr(cfg)
    # The nested object is not redacted wholesale — its non-secret fields stay visible.
    assert "project_id='my-project'" in rendered
    assert "client_email='sa@example.com'" in rendered
    # The actual secret inside the nested config is still redacted.
    assert "BEGIN" not in rendered
    assert "private_key='***'" in rendered


def test_validate_dict():
    @config.config
    class TestConfig(config.Config):
        a: str

    config_dict = {
        "b": "test",
    }

    is_valid, errors = TestConfig.validate_dict(config_dict)

    assert is_valid is False
    assert len(errors) == 1

    config_dict = {
        "a": "test",
    }

    is_valid, errors = TestConfig.validate_dict(config_dict)

    assert is_valid is True
    assert len(errors) == 0


def test_validate_dict_alias():
    @config.config
    class TestConfig(config.Config):
        a: str = config.value(alias="c")

    config_dict = {
        "b": "test",
    }

    is_valid, errors = TestConfig.validate_dict(config_dict)

    assert is_valid is False
    assert len(errors) == 1

    config_dict = {
        "c": "test",
    }

    is_valid, errors = TestConfig.validate_dict(config_dict)

    assert is_valid is True
    assert len(errors) == 0


def test_validate_dict_default():
    @config.config
    class TestConfig(config.Config):
        a: str = config.value(default="1")

    config_dict = {
        "b": "test",
    }

    is_valid, errors = TestConfig.validate_dict(config_dict)

    assert is_valid is True
    assert len(errors) == 0


def test_validate_dict_with_nested_dict():
    @config.config
    class TestConfigA:
        a: str
        b: int = 0
        c: str | None = None

    @config.config
    class TestConfigB:
        a: TestConfigA

    @config.config
    class TestConfigC(config.Config):
        a: TestConfigA
        b: TestConfigB
        d: bool = False

    config_dict = {
        "a": {
            "a": "test",
        },
        "b": {
            "a": {
                "a": "test",
                "b": 1,
                "c": "something",
            }
        },
        "d": True,
    }

    is_valid, errors = TestConfigC.validate_dict(config_dict)

    assert is_valid is True
    assert len(errors) == 0

    config_dict = {
        "a": {
            "non_existent_key": "test",
        },
        "b": {
            "a": {
                "a": "test",
                "b": 1,
                "c": "something",
            }
        },
        "d": True,
    }

    is_valid, errors = TestConfigC.validate_dict(config_dict)

    assert is_valid is False
    assert len(errors) == 1

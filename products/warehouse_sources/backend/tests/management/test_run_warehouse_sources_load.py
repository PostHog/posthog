from parameterized import parameterized

from products.warehouse_sources.backend.management.commands.run_warehouse_sources_load import (
    Command,
    build_consumer_config,
)


def _parse_options(argv: list[str]) -> dict:
    parser = Command().create_parser("manage.py", "run_warehouse_sources_load")
    return vars(parser.parse_args(argv))


class TestBuildConsumerConfig:
    def test_defaults_come_from_the_config_dataclass(self):
        config = build_consumer_config(_parse_options([]))

        assert config.poll_timeout_seconds == 180.0
        assert config.sweep_timeout_seconds == 300.0
        assert config.connect_timeout_seconds == 10
        assert config.recovery_grace_seconds == 300
        assert config.lease_ttl_seconds == config.recovery_grace_seconds

    @parameterized.expand(
        [
            (["--poll-timeout", "600"], "poll_timeout_seconds", 600.0),
            (["--poll-timeout", "0"], "poll_timeout_seconds", None),
            (["--sweep-timeout", "900"], "sweep_timeout_seconds", 900.0),
            (["--sweep-timeout", "0"], "sweep_timeout_seconds", None),
            (["--connect-timeout", "30"], "connect_timeout_seconds", 30),
            (["--lease-ttl", "600"], "lease_ttl_seconds", 600),
            (["--recovery-grace", "900"], "recovery_grace_seconds", 900),
        ]
    )
    def test_flag_overrides_reach_the_config(self, argv: list[str], field: str, expected):
        config = build_consumer_config(_parse_options(argv))

        assert getattr(config, field) == expected

    def test_lease_ttl_follows_recovery_grace_when_not_set(self):
        config = build_consumer_config(_parse_options(["--recovery-grace", "900"]))

        assert config.lease_ttl_seconds == 900

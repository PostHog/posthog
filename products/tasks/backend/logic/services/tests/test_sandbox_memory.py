from parameterized import parameterized

from products.tasks.backend.logic.services.sandbox_memory import (
    MemoryPressureLevel,
    memory_pressure_level,
    parse_memory_probe,
)

GIB = 1024**3


def _probe(**sections: str) -> str:
    return "".join(f"@@{name}\n{content}\n" for name, content in sections.items())


def _meminfo(total_kb: int, available_kb: int) -> str:
    return f"MemTotal:       {total_kb} kB\nMemFree:        1000 kB\nMemAvailable:   {available_kb} kB\n"


class TestParseMemoryProbe:
    @parameterized.expand(
        [
            # A container's cgroup ceiling is the one the kernel enforces, and /proc/meminfo
            # reports the whole host. Taking the host total here would keep the guard silent
            # on every container.
            (
                "container_prefers_its_cgroup_ceiling_over_the_host_total",
                {
                    "cgroup2_current": str(6 * GIB),
                    "cgroup2_max": str(8 * GIB),
                    "meminfo": _meminfo(total_kb=256 * 1024 * 1024, available_kb=200 * 1024 * 1024),
                },
                8 * GIB,
                6 * GIB,
                "cgroup_v2",
            ),
            # A VM-backed sandbox has no cgroup ceiling, so the kernel's own total is the
            # only answer. This is the shape that runs a local dev stack.
            (
                "vm_falls_back_to_the_kernel_total_when_the_cgroup_is_unlimited",
                {
                    "cgroup2_current": str(2 * GIB),
                    "cgroup2_max": "max",
                    "meminfo": _meminfo(total_kb=16 * 1024 * 1024, available_kb=4 * 1024 * 1024),
                },
                16 * GIB,
                12 * GIB,
                "meminfo",
            ),
            (
                "cgroup_v1_file_names_are_read_too",
                {
                    "cgroup1_current": str(3 * GIB),
                    "cgroup1_max": str(4 * GIB),
                },
                4 * GIB,
                3 * GIB,
                "cgroup_v1",
            ),
            # cgroup v1 writes a huge sentinel rather than a word when nothing limits the box.
            (
                "cgroup_v1_sentinel_is_not_treated_as_a_ceiling",
                {
                    "cgroup1_current": str(2 * GIB),
                    "cgroup1_max": "9223372036854771712",
                    "meminfo": _meminfo(total_kb=8 * 1024 * 1024, available_kb=2 * 1024 * 1024),
                },
                8 * GIB,
                6 * GIB,
                "meminfo",
            ),
            # A ceiling smaller than the cgroup's still binds: the box cannot use memory the
            # kernel does not have.
            (
                "the_narrowest_ceiling_wins",
                {
                    "cgroup2_current": str(1 * GIB),
                    "cgroup2_max": str(64 * GIB),
                    "meminfo": _meminfo(total_kb=4 * 1024 * 1024, available_kb=1 * 1024 * 1024),
                },
                4 * GIB,
                3 * GIB,
                "meminfo",
            ),
        ]
    )
    def test_it_picks_the_ceiling_the_box_is_actually_bound_by(
        self, _name: str, sections: dict[str, str], limit_bytes: int, used_bytes: int, source: str
    ) -> None:
        memory = parse_memory_probe(_probe(**sections))

        assert memory is not None
        assert memory.limit_bytes == limit_bytes
        assert memory.used_bytes == used_bytes
        assert memory.source == source

    @parameterized.expand(
        [
            ("nothing_readable", {}),
            ("usage_without_a_ceiling", {"cgroup2_current": str(GIB)}),
            ("non_numeric_values", {"cgroup2_current": "unknown", "cgroup2_max": "unknown"}),
            ("meminfo_without_the_available_field", {"meminfo": "MemTotal:       16384 kB\n"}),
        ]
    )
    def test_an_unreadable_probe_is_unknown_rather_than_healthy(self, _name: str, sections: dict[str, str]) -> None:
        assert parse_memory_probe(_probe(**sections)) is None

    def test_it_names_the_processes_holding_the_memory(self) -> None:
        memory = parse_memory_probe(
            _probe(
                cgroup2_current=str(7 * GIB),
                cgroup2_max=str(8 * GIB),
                cgroup2_events="low 0\nhigh 12\nmax 3\noom 1\noom_kill 2\n",
                processes="6291456 dockerd\n1048576 node\ngarbage line\n",
            )
        )

        assert memory is not None
        assert memory.oom_kills == 2
        assert [(process.name, process.resident_bytes) for process in memory.top_processes] == [
            ("dockerd", 6 * GIB),
            ("node", GIB),
        ]

    def test_usage_above_the_ceiling_is_clamped(self) -> None:
        memory = parse_memory_probe(_probe(cgroup2_current=str(9 * GIB), cgroup2_max=str(8 * GIB)))

        assert memory is not None
        assert memory.used_bytes == 8 * GIB
        assert memory.used_percent == 100


class TestMemoryPressureLevel:
    @parameterized.expand(
        [
            (0.0, MemoryPressureLevel.OK),
            (0.699, MemoryPressureLevel.OK),
            (0.70, MemoryPressureLevel.WATCH),
            (0.849, MemoryPressureLevel.WATCH),
            (0.85, MemoryPressureLevel.WARNING),
            (0.929, MemoryPressureLevel.WARNING),
            (0.93, MemoryPressureLevel.CRITICAL),
            (1.0, MemoryPressureLevel.CRITICAL),
        ]
    )
    def test_each_threshold_is_inclusive(self, fraction: float, expected: MemoryPressureLevel) -> None:
        assert memory_pressure_level(fraction) == expected

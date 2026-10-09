from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.facade.compute import (
    DEFAULT_SANDBOX_SIZE,
    SANDBOX_SIZE_SHAPES,
    SandboxSize,
    parse_sandbox_size,
)
from products.tasks.backend.logic.services.sandbox import SandboxConfig
from products.tasks.backend.logic.services.sandbox_config import MAX_SANDBOX_CPU_CORES, MAX_SANDBOX_MEMORY_GB


class TestSandboxSize(SimpleTestCase):
    @parameterized.expand(
        [
            ("1x2", 1.0, 2.0),
            ("2x4", 2.0, 4.0),
            ("2x8", 2.0, 8.0),
            ("4x8", 4.0, 8.0),
            ("4x16", 4.0, 16.0),
            ("8x16", 8.0, 16.0),
            ("8x32", 8.0, 32.0),
            ("16x64", 16.0, 64.0),
        ]
    )
    def test_size_parses_to_its_shape(self, value: str, cpu_cores: float, memory_gb: float) -> None:
        shape = SANDBOX_SIZE_SHAPES[parse_sandbox_size(value)]

        assert (shape.cpu_cores, shape.memory_gb) == (cpu_cores, memory_gb)

    @parameterized.expand([("",), ("4X16",), ("4x16 ",), ("16x16",), ("32x128",), ("large",)])
    def test_unknown_size_is_refused(self, value: str) -> None:
        with self.assertRaises(ValueError):
            parse_sandbox_size(value)

    def test_every_size_has_a_shape_inside_the_override_bounds(self) -> None:
        # A shape over a bound is clamped at provision time, so the run would get a smaller
        # box than the size it is billed for.
        assert set(SANDBOX_SIZE_SHAPES) == set(SandboxSize)
        for shape in SANDBOX_SIZE_SHAPES.values():
            assert shape.cpu_cores is not None and 0 < shape.cpu_cores <= MAX_SANDBOX_CPU_CORES
            assert shape.memory_gb is not None and 0 < shape.memory_gb <= MAX_SANDBOX_MEMORY_GB

    def test_default_size_is_the_default_sandbox_shape(self) -> None:
        config = SandboxConfig(name="default")
        shape = SANDBOX_SIZE_SHAPES[DEFAULT_SANDBOX_SIZE]

        assert (shape.cpu_cores, shape.memory_gb) == (config.cpu_cores, config.memory_gb)

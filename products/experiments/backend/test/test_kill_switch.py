from unittest.mock import patch

from django.db import OperationalError
from django.test import SimpleTestCase

from products.experiments.backend.recalculation.kill_switch import recalculation_enabled


class TestRecalculationEnabled(SimpleTestCase):
    def test_a_failed_setting_read_counts_as_enabled(self):
        with patch(
            "products.experiments.backend.recalculation.kill_switch.get_instance_setting",
            side_effect=OperationalError("connection lost"),
        ):
            assert recalculation_enabled() is True

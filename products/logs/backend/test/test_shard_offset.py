from parameterized import parameterized

from posthog.test.clickhouse_free import ClickhouseFreeSimpleTestCase

from products.logs.backend.alert_utils import compute_shard_offset_seconds


class TestComputeShardOffsetSeconds(ClickhouseFreeSimpleTestCase):
    @parameterized.expand([(1,), (5,), (15,), (60,)])
    def test_team_offsets_cover_every_minute_slot_of_the_cadence(self, cadence: int) -> None:
        offsets = {compute_shard_offset_seconds(team_id, cadence) for team_id in range(1, 2001)}
        assert offsets == {slot * 60 for slot in range(cadence)}

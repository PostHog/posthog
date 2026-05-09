from uuid import UUID

import temporalio.activity

from posthog.sync import database_sync_to_async

from products.replay_vision.backend.models.replay_lens import ReplayLens
from products.replay_vision.backend.temporal.lenses import get_lens_impl
from products.replay_vision.backend.temporal.types import FinalLensOutput, SegmentLensOutput


@temporalio.activity.defn
async def consolidate_lens_segments_activity(
    lens_id: UUID,
    segment_outputs: list[SegmentLensOutput],
) -> FinalLensOutput:
    @database_sync_to_async
    def _load_lens() -> ReplayLens:
        return ReplayLens.objects.get(id=lens_id)

    lens = await _load_lens()
    impl = get_lens_impl(lens.lens_type)
    parsed = [impl.SegmentOutput.model_validate_json(s.output_json) for s in segment_outputs]
    final = await impl.consolidate(parsed, lens.lens_config)
    return FinalLensOutput(output_json=final.model_dump_json(), confidence=final.confidence)

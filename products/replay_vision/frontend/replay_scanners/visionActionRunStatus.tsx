import { LemonTag } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import type { VisionActionRunStatusEnumApi } from '../generated/api.schemas'

const STATUS_TAG: Record<
    VisionActionRunStatusEnumApi,
    { type: 'success' | 'danger' | 'warning' | 'primary'; label: string }
> = {
    completed: { type: 'success', label: 'Completed' },
    failed: { type: 'danger', label: 'Failed' },
    skipped: { type: 'warning', label: 'Skipped' },
    running: { type: 'primary', label: 'Running' },
}

// Single source of truth for how a run's status renders — used by the run list and the run detail page.
// Pass `reason` (a skipped/failed run's error_reason) to surface it as a tooltip on the chip.
export function RunStatusTag({
    status,
    reason,
}: {
    status: VisionActionRunStatusEnumApi
    reason?: string | null
}): JSX.Element {
    const tag = STATUS_TAG[status]
    const chip = (
        <LemonTag type={tag.type} size="small">
            {tag.label}
        </LemonTag>
    )
    return reason ? <Tooltip title={reason}>{chip}</Tooltip> : chip
}

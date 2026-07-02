import { LemonTag } from '@posthog/lemon-ui'

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
export function RunStatusTag({ status }: { status: VisionActionRunStatusEnumApi }): JSX.Element {
    const tag = STATUS_TAG[status]
    return (
        <LemonTag type={tag.type} size="small">
            {tag.label}
        </LemonTag>
    )
}

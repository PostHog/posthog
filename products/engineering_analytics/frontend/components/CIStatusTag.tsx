import { LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { CIRollup, CIStatus, ciStatusOf } from '../lib/ci'

const STATUS_CONFIG: Record<CIStatus, { label: string; type: LemonTagType }> = {
    passing: { label: 'Passing', type: 'success' },
    failing: { label: 'Failing', type: 'danger' },
    running: { label: 'Running', type: 'warning' },
    none: { label: 'No CI', type: 'muted' },
}

export function CIStatusTag({ rollup }: { rollup: CIRollup }): JSX.Element {
    const config = STATUS_CONFIG[ciStatusOf(rollup)]
    return (
        <div className="flex items-center gap-2">
            <LemonTag type={config.type}>{config.label}</LemonTag>
            {rollup.runs > 0 && (
                <Tooltip title="Workflow-level rollup over the PR's head commit — not per-check. A run that has not completed counts as pending.">
                    <span className="font-mono text-xs text-secondary whitespace-nowrap">
                        {rollup.passing}✓ {rollup.failing}✗ {rollup.pending}…
                    </span>
                </Tooltip>
            )}
        </div>
    )
}

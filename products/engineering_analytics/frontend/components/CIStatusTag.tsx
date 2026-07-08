import { IconCheck, IconClock, IconX } from '@posthog/icons'
import { LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { CIRollup, CIStatus, ciStatusOf } from '../lib/ci'

const STATUS_CONFIG: Record<CIStatus, { label: string; type: LemonTagType }> = {
    passing: { label: 'Passing', type: 'success' },
    failing: { label: 'Failing', type: 'danger' },
    running: { label: 'Running', type: 'warning' },
    none: { label: 'No CI', type: 'muted' },
}

function Count({ count, icon, className }: { count: number; icon: JSX.Element; className: string }): JSX.Element {
    return (
        <span className={`flex items-center gap-0.5 text-xs whitespace-nowrap ${className}`}>
            {icon}
            {count}
        </span>
    )
}

export function CIStatusTag({ rollup }: { rollup: CIRollup }): JSX.Element {
    const config = STATUS_CONFIG[ciStatusOf(rollup)]
    return (
        <div className="flex items-center gap-2">
            <LemonTag type={config.type}>{config.label}</LemonTag>
            {rollup.runs > 0 && (
                <Tooltip
                    title={`${rollup.passing} passed, ${rollup.failing} failed, ${rollup.pending} still running. Workflow-level status for the PR's latest commit, not per-check.`}
                >
                    <span className="flex items-center gap-1.5">
                        {rollup.passing > 0 && (
                            <Count count={rollup.passing} icon={<IconCheck />} className="text-success" />
                        )}
                        {rollup.failing > 0 && (
                            <Count count={rollup.failing} icon={<IconX />} className="text-danger" />
                        )}
                        {rollup.pending > 0 && (
                            <Count count={rollup.pending} icon={<IconClock />} className="text-secondary" />
                        )}
                    </span>
                </Tooltip>
            )}
        </div>
    )
}

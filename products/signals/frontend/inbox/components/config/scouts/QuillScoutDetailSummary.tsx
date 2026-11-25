import { Badge } from '@posthog/quill'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import { scoutPausedByLine, scoutTurnedOnByLine } from '../../../utils/scoutGroups'
import { ScoutRollup } from '../../../utils/scoutRunsWindow'
import { ScoutExemptionBadge } from './ScoutBadges'
import { ScoutHealthStrip } from './ScoutHealthStrip'
import { ScoutOwners } from './ScoutOwners'
import { ScoutStatusChangeLine } from './ScoutStatusChangeLine'

export function QuillScoutDetailSummary({
    config,
    rollup,
    noteCount,
    learnedCount,
}: {
    config: SignalScoutConfig
    rollup: ScoutRollup | undefined
    noteCount: number
    learnedCount: number
}): JSX.Element {
    return (
        <div className="flex flex-col gap-3 border-b border-primary px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
                <Badge variant={config.scout_origin === 'canonical' ? 'default' : 'info'}>
                    {config.scout_origin === 'canonical' ? 'Canonical' : 'Custom'}
                </Badge>
                {/* The page has no roster group, and the role is not a windowed judgment anyway. */}
                <ScoutExemptionBadge config={config} group="watching" />
                <ScoutOwners config={config} />
            </div>
            <ScoutStatusChangeLine config={config} line={scoutPausedByLine(config) ?? scoutTurnedOnByLine(config)} />
            <ScoutHealthStrip config={config} rollup={rollup} noteCount={noteCount} learnedCount={learnedCount} />
        </div>
    )
}

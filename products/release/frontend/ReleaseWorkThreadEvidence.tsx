import { useValues } from 'kea'
import { useMemo } from 'react'

import type { WorkStepApi } from 'products/today/frontend/generated/api.schemas'

import { ReleaseLaneCard } from './ReleaseLaneCard'
import { releaseMetricsLogic } from './releaseMetricsLogic'
import { ReleaseMetricTile } from './ReleaseMetricTile'
import { releaseRelatedLogic } from './releaseRelatedLogic'
import { buildTrack } from './releaseTracks'
import { CALENDAR_DAYS_AFTER, ReleaseRow } from './releaseUtils'
import { useRolloutStepsByFlag } from './useRolloutStepsByFlag'

// Each prefix must match the lane key that buildTrack writes, or the lookup below finds no lane.
const LANE_PREFIX: Record<string, string> = {
    feature_flag: 'flag',
    experiment: 'experiment',
    early_access_feature: 'early-access',
    survey: 'survey',
}

export function ReleaseWorkThreadEvidence({ step, row }: { step: WorkStepApi; row: ReleaseRow }): JSX.Element | null {
    const { relatedByRelease } = useValues(releaseRelatedLogic)
    const { metrics } = useValues(releaseMetricsLogic)
    const stepsByFlag = useRolloutStepsByFlag(CALENDAR_DAYS_AFTER)
    const related = relatedByRelease[row.id]
    const lanes = useMemo(() => buildTrack(row, stepsByFlag, related).lanes, [row, stepsByFlag, related])
    const item = step.item

    if (!item) {
        return null
    }

    if (item.type === 'release' || item.type === 'insight') {
        const insightId = item.type === 'release' ? row.metricInsightIds[0] : Number(item.id)
        if (insightId === undefined || !row.metricInsightIds.includes(insightId) || !metrics[insightId]) {
            return null
        }
        return <ReleaseMetricTile row={row} insightId={insightId} primary={insightId === row.metricInsightIds[0]} />
    }

    const prefix = LANE_PREFIX[item.type]
    const lane = prefix ? lanes.find((candidate) => candidate.key === `${prefix}-${item.id}`) : undefined
    if (!lane) {
        return null
    }

    if (lane.kind === 'flag') {
        const past = lane.steps.filter((rollout) => !rollout.upcoming)
        const current = past[past.length - 1]
        return current ? (
            <ReleaseLaneCard
                lane={lane}
                step={current}
                next={lane.steps.find((rollout) => rollout.upcoming && rollout.from > current.from)}
            />
        ) : (
            <ReleaseLaneCard lane={lane} span={lane.span} />
        )
    }

    if (lane.kind === 'survey') {
        return <ReleaseLaneCard lane={lane} />
    }

    return lane.kind !== 'broadcast' && lane.span ? <ReleaseLaneCard lane={lane} span={lane.span} /> : null
}

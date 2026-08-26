// Where a change's time goes on the way to production, as bars sharing one scale.

import { LemonCard, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import type { DeliveryPipelineApi, DeliveryStageTimingApi } from '../generated/api.schemas'
import { DeliveryStageTimingStageEnumApi } from '../generated/api.schemas'
import { compactAgeLabel, compactCount } from '../lib/format'
import { ShareRow } from './ShareRow'

interface LegCopy {
    label: string
    sub: string
    tooltip: string
}

const LEG_COPY: Record<DeliveryStageTimingApi['stage'], LegCopy> = {
    [DeliveryStageTimingStageEnumApi.OpenToGate]: {
        label: 'Open to merge queue',
        sub: 'Review, changes, and waiting for a slot',
        tooltip:
            'From the PR opening to its first merge queue gate run starting. Nothing records when a PR joined the queue, so this is the earliest queue activity we can see and everything before it is folded in.',
    },
    [DeliveryStageTimingStageEnumApi.GateToMerge]: {
        label: 'In the merge queue',
        sub: 'Gate runs until the PR merges',
        tooltip: 'From the first gate run starting to the PR merging. Retried attempts are included.',
    },
}

const MERGE_TO_DEPLOY_COPY: LegCopy = {
    label: 'Merge to production',
    sub: 'Waiting for the deploy that ships it',
    tooltip:
        'From the merge to the first successful production deploy that contains it, resolved through the deploy head commit. The same measure as the Health tab.',
}

export interface MergeToDeployLeg {
    medianSeconds: number | null
    prCount: number
}

interface RenderedLeg {
    key: string
    copy: LegCopy
    medianSeconds: number
    p90Seconds: number | null
    prCount: number
}

export function DeliveryPipeline({
    pipeline,
    mergeToDeploy,
    loading = false,
}: {
    pipeline: DeliveryPipelineApi | null | undefined
    /** The post-merge leg, read from the DORA endpoint. Null while loading or when deploy data is not synced. */
    mergeToDeploy: MergeToDeployLeg | null
    loading?: boolean
}): JSX.Element {
    if (!pipeline) {
        return (
            <LemonCard hoverEffect={false} className="flex h-full flex-col gap-3 p-3">
                {[0, 1, 2].map((row) => (
                    <LemonSkeleton key={row} className="h-8 w-full" active={loading} />
                ))}
            </LemonCard>
        )
    }
    const legs: RenderedLeg[] = pipeline.stages
        .filter((leg) => leg.median_seconds != null)
        .map((leg) => ({
            key: leg.stage,
            copy: LEG_COPY[leg.stage],
            medianSeconds: leg.median_seconds ?? 0,
            p90Seconds: leg.p90_seconds ?? null,
            prCount: leg.pr_count,
        }))
    if (mergeToDeploy?.medianSeconds != null) {
        legs.push({
            key: 'merge_to_deploy',
            copy: MERGE_TO_DEPLOY_COPY,
            medianSeconds: mergeToDeploy.medianSeconds,
            p90Seconds: null,
            prCount: mergeToDeploy.prCount,
        })
    }
    if (legs.length === 0) {
        return (
            <LemonCard hoverEffect={false} className="flex h-full items-center p-4 text-xs text-secondary">
                {pipeline.merged_pr_count === 0
                    ? 'Nothing merged in the window.'
                    : 'No merged PR in the window has a measurable step yet.'}
            </LemonCard>
        )
    }
    // One scale across the legs, so a bar's length compares it against the slowest one.
    const slowest = Math.max(...legs.map((leg) => leg.medianSeconds))
    return (
        <LemonCard hoverEffect={false} className="h-full p-2">
            {legs.map((leg) => (
                <ShareRow
                    key={leg.key}
                    fullWidthBar
                    label={<Tooltip title={leg.copy.tooltip}>{leg.copy.label}</Tooltip>}
                    sub={leg.copy.sub}
                    share={slowest > 0 ? leg.medianSeconds / slowest : 0}
                    color={leg.medianSeconds === slowest ? 'var(--data-color-1)' : 'var(--muted)'}
                    value={compactAgeLabel(leg.medianSeconds)}
                    valueSub={
                        leg.p90Seconds != null
                            ? `p90 ${compactAgeLabel(leg.p90Seconds)} · ${compactCount(leg.prCount)} PRs`
                            : `${compactCount(leg.prCount)} PRs`
                    }
                />
            ))}
        </LemonCard>
    )
}

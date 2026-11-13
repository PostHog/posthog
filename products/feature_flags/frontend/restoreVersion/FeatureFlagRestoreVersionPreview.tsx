import { LemonBanner } from '@posthog/lemon-ui'

import { objectsEqual } from 'lib/utils/objects'

import { FeatureFlagFilters, FeatureFlagType } from '~/types'

import { FeatureFlagReleaseConditionsChange } from '../FeatureFlagReleaseConditionsChange'
import type { FeatureFlagVersionResponseApi } from '../generated/api.schemas'

export interface FeatureFlagRestoreVersionPreviewProps {
    flag: FeatureFlagType
    target: FeatureFlagVersionResponseApi
}

// Restored settings that the release conditions diff below does not show.
const OTHER_RESTORED_SETTINGS = [
    ['is_remote_configuration', 'Flag type'],
    ['ensure_experience_continuity', 'Persist flag across authentication steps'],
    ['bucketing_identifier', 'Bucketing identifier'],
    ['evaluation_runtime', 'Evaluation runtime'],
    ['has_enriched_analytics', 'Enriched analytics'],
] as const

function otherRestoredChanges(flag: FeatureFlagType, target: FeatureFlagVersionResponseApi): string[] {
    return [
        ...(objectsEqual(target.filters?.multivariate ?? null, flag.filters.multivariate ?? null) ? [] : ['Variants']),
        ...(objectsEqual(target.filters?.payloads ?? {}, flag.filters.payloads ?? {}) ? [] : ['Payloads']),
        ...OTHER_RESTORED_SETTINGS.filter(([field]) => (target[field] || null) !== (flag[field] || null)).map(
            ([, label]) => label
        ),
    ]
}

export function FeatureFlagRestoreVersionPreview({ flag, target }: FeatureFlagRestoreVersionPreviewProps): JSX.Element {
    const hasRunningExperiment = (flag.experiment_set_metadata ?? []).some((experiment) => experiment.is_running)
    const nameChanges = (target.name ?? '') !== (flag.name ?? '')
    const otherChanges = otherRestoredChanges(flag, target)

    return (
        <div className="flex flex-col gap-3">
            <p className="m-0">
                The flag's release conditions, variants, payloads, description and evaluation options go back to what
                they were in this version. The restore is saved as a new version, so you can undo it from the history.
            </p>
            {hasRunningExperiment && (
                <LemonBanner type="warning">
                    This flag runs an experiment. Changing its rollout or variants can change who is exposed and affect
                    the results.
                </LemonBanner>
            )}
            {nameChanges && (
                <div>
                    <div className="font-semibold">Description</div>
                    <div className="text-secondary">{target.name || 'No description'}</div>
                </div>
            )}
            <div>
                <div className="font-semibold mb-1">Release conditions in this version</div>
                <FeatureFlagReleaseConditionsChange
                    flagId={String(flag.id)}
                    activityId={`restore-${target.version}`}
                    before={flag.filters as FeatureFlagFilters}
                    after={target.filters as unknown as FeatureFlagFilters}
                />
            </div>
            {otherChanges.length > 0 && (
                <div>
                    <div className="font-semibold">Also changes</div>
                    <div className="text-secondary">{otherChanges.join(', ')}</div>
                </div>
            )}
            <LemonBanner type="info">
                These stay as they are now: whether the flag is enabled, its key, tags, evaluation contexts, schedules,
                early access enrollment, experiment holdouts, and how the cohorts it targets are defined.
            </LemonBanner>
        </div>
    )
}

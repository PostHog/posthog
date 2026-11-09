import { LemonBanner } from '@posthog/lemon-ui'

import { FeatureFlagFilters, FeatureFlagType } from '~/types'

import { FeatureFlagReleaseConditionsChange } from '../FeatureFlagReleaseConditionsChange'
import type { FeatureFlagVersionResponseApi } from '../generated/api.schemas'

export interface FeatureFlagRestoreVersionPreviewProps {
    flag: FeatureFlagType
    target: FeatureFlagVersionResponseApi
}

export function FeatureFlagRestoreVersionPreview({ flag, target }: FeatureFlagRestoreVersionPreviewProps): JSX.Element {
    const hasRunningExperiment = (flag.experiment_set_metadata ?? []).some((experiment) => experiment.is_running)
    const nameChanges = (target.name ?? '') !== (flag.name ?? '')

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
            <LemonBanner type="info">
                These stay as they are now: whether the flag is enabled, its key, tags, evaluation contexts, schedules,
                and how the cohorts it targets are defined.
            </LemonBanner>
        </div>
    )
}

import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { userHasAccess } from 'lib/utils/accessControlUtils'
import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { exposureCriteriaModalLogic } from 'scenes/experiments/ExperimentView/exposureCriteriaModalLogic'
import { modalsLogic } from 'scenes/experiments/modalsLogic'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { METRIC_CONTEXTS } from '../modals/ExperimentMetricModal/experimentMetricModalLogic'
import { metricSourceModalLogic } from '../modals/MetricSourceModal/metricSourceModalLogic'
import type { ExperimentHealthFindingActionKind } from './experimentHealthFindingEvents'

export function HealthFindingActionButton({
    actionKind,
    onClick,
}: {
    actionKind: ExperimentHealthFindingActionKind
    onClick: () => void
}): JSX.Element | null {
    const { experiment, exposureCriteria } = useValues(experimentLogic)
    const { openDistributionModal } = useActions(modalsLogic)
    const { openExposureCriteriaModal } = useActions(exposureCriteriaModalLogic)
    const { openMetricSourceModal } = useActions(metricSourceModalLogic)

    const canEdit = userHasAccess(
        AccessControlResourceType.Experiment,
        AccessControlLevel.Editor,
        experiment.user_access_level
    )
    const buttonProps = {
        size: 'small',
        type: 'secondary',
        // pinned: `data-attr` value, so renaming it breaks autocapture insights
        'data-attr': `experiment-health-action-${actionKind}`,
    } as const
    // Every action except the flag link opens a form that saves the experiment.
    const editProps = {
        ...buttonProps,
        disabledReason: canEdit ? null : "You don't have permission to edit this experiment.",
    }

    switch (actionKind) {
        case 'open_feature_flag':
            return experiment.feature_flag ? (
                <LemonButton
                    {...buttonProps}
                    to={urls.featureFlag(experiment.feature_flag.id)}
                    targetBlank
                    onClick={onClick}
                >
                    Open feature flag
                </LemonButton>
            ) : null
        case 'adjust_distribution':
            return (
                <LemonButton
                    {...editProps}
                    onClick={() => {
                        onClick()
                        openDistributionModal()
                    }}
                >
                    Adjust distribution
                </LemonButton>
            )
        case 'use_first_seen_variant':
            return (
                <LemonButton
                    {...editProps}
                    onClick={() => {
                        onClick()
                        openExposureCriteriaModal({ ...exposureCriteria, multiple_variant_handling: 'first_seen' })
                    }}
                >
                    Use first seen variant
                </LemonButton>
            )
        case 'edit_exposure_criteria':
            return (
                <LemonButton
                    {...editProps}
                    onClick={() => {
                        onClick()
                        openExposureCriteriaModal(exposureCriteria)
                    }}
                >
                    Edit exposure criteria
                </LemonButton>
            )
        case 'add_primary_metric':
            return (
                <LemonButton
                    {...editProps}
                    onClick={() => {
                        onClick()
                        openMetricSourceModal(METRIC_CONTEXTS.primary)
                    }}
                >
                    Add primary metric
                </LemonButton>
            )
        case 'add_secondary_metric':
            return (
                <LemonButton
                    {...editProps}
                    onClick={() => {
                        onClick()
                        openMetricSourceModal(METRIC_CONTEXTS.secondary)
                    }}
                >
                    Add secondary metric
                </LemonButton>
            )
    }
}

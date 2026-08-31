import { LemonButton, LemonCollapse } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type {
    PulseRunHistoryDTOApi,
    RunActionHistoryDTOApi,
} from 'products/subscriptions/frontend/generated/api.schemas'

import { SubscriptionPulseArtifacts } from './SubscriptionPulseArtifacts'
import { SubscriptionPulseBuildTestGate } from './SubscriptionPulseBuildTestGate'
import {
    actionStatusLabel,
    failedArtifacts,
    failureMessage,
    isPreparationFailure,
    isUnpreparedAction,
} from './subscriptionPulseDeliveryUtils'
import { SubscriptionPulseEvidence } from './SubscriptionPulseEvidence'

export function SubscriptionPulseOperationalDetails({
    run,
    actions,
}: {
    run: PulseRunHistoryDTOApi
    actions: RunActionHistoryDTOApi[]
}): JSX.Element | null {
    const runFailure = failureMessage(run.failure_code)
    const preparationActions = actions.filter((action) => isUnpreparedAction(action) || isPreparationFailure(action))
    const hasDetails =
        run.task_id ||
        runFailure ||
        preparationActions.length > 0 ||
        actions.some((action) => action.evidence.length > 0 || action.citations.length > 0 || action.build_test_gate)
    if (!hasDetails) {
        return null
    }
    return (
        <LemonCollapse
            size="small"
            panels={[
                {
                    key: 'operational-details',
                    header: 'Operational details',
                    content: (
                        <div className="text-xs text-secondary flex flex-col gap-2">
                            {run.task_id ? (
                                <div>
                                    <LemonButton type="tertiary" size="xsmall" to={urls.taskDetail(run.task_id)}>
                                        View analysis task
                                    </LemonButton>
                                </div>
                            ) : null}
                            {runFailure ? <span className="text-warning">{runFailure}</span> : null}
                            {actions.map((action) => (
                                <SubscriptionPulseEvidence key={`evidence-${action.id}`} action={action} />
                            ))}
                            {actions.map((action) => (
                                <SubscriptionPulseBuildTestGate key={`gate-${action.id}`} action={action} />
                            ))}
                            {preparationActions.map((action) => (
                                <div key={`preparation-${action.id}`} className="flex flex-col gap-1">
                                    <span>
                                        <span className="font-medium text-primary">{action.title}</span>: preparation{' '}
                                        {actionStatusLabel(action.status)}.
                                    </span>
                                    {failedArtifacts(action).length > 0 ? (
                                        <SubscriptionPulseArtifacts artifacts={failedArtifacts(action)} />
                                    ) : null}
                                    {isUnpreparedAction(action) && failedArtifacts(action).length === 0 ? (
                                        <span>Pulse did not create a prepared artifact.</span>
                                    ) : null}
                                    {failedArtifacts(action)
                                        .map((artifact) => failureMessage(artifact.failure_code))
                                        .filter((failure): failure is string => Boolean(failure))
                                        .map((failure, index) => (
                                            <span key={`${action.id}-failure-${index}`} className="text-danger">
                                                {failure}
                                            </span>
                                        ))}
                                </div>
                            ))}
                        </div>
                    ),
                },
            ]}
        />
    )
}

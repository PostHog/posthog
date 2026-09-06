import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonModal } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import { subscriptionLogic } from '../../components/Subscriptions/subscriptionLogic'
import { SubscriptionWizard } from '../../components/Subscriptions/SubscriptionWizard'
import { requestSubscriptionWizardCancellation } from '../../components/Subscriptions/utils'
import { EditSubscription, SubscriptionFormSkeleton } from '../../components/Subscriptions/views/EditSubscription'
import { newSubscriptionTargetLogic } from '../newSubscriptionTargetLogic'
import { subscriptionsSceneLogic } from '../subscriptionsSceneLogic'
import { NewSubscriptionTarget } from './NewSubscriptionTarget'

/**
 * The create and edit modal the subscriptions route opens over whatever is on screen.
 * It renders from the URL alone, so the setup empty state can show it too - the scene
 * behind it is not rendered while the gate is up.
 */
export function SubscriptionsSceneModal(): JSX.Element | null {
    const { subscriptionModalId, aiSubscriptionsAvailable } = useValues(subscriptionsSceneLogic)
    const {
        target: newSubscriptionTarget,
        dashboard: newSubscriptionDashboard,
        dashboardLoading: newSubscriptionDashboardLoading,
    } = useValues(newSubscriptionTargetLogic)
    const { reset: resetNewSubscriptionTarget } = useActions(newSubscriptionTargetLogic)
    const subscriptionWizardExperimentEnabled = useFeatureFlag('SUBSCRIPTION_CREATION_WIZARD', 'test')

    const isWizard = subscriptionModalId === 'new' && subscriptionWizardExperimentEnabled
    const insightTarget = newSubscriptionTarget?.kind === 'insight' ? newSubscriptionTarget : null
    const dashboardTargetPending = newSubscriptionTarget?.kind === 'dashboard' && !newSubscriptionDashboard
    // A dashboard that failed to load leaves nothing to send, so the picker comes back.
    const isPickingTarget =
        subscriptionModalId === 'new' &&
        (newSubscriptionTarget === null || (dashboardTargetPending && !newSubscriptionDashboardLoading))

    const cancel = (): void => {
        resetNewSubscriptionTarget()
        router.actions.push(urls.subscriptions())
    }
    const requestWizardCancel = (): void => {
        const wizardForm = subscriptionLogic.findMounted({ id: 'new', creationSource: 'wizard' })
        if (!wizardForm) {
            cancel()
            return
        }
        requestSubscriptionWizardCancellation({
            onCancel: cancel,
            resetSubscription: () => wizardForm.actions.resetSubscription(),
            subscriptionChanged: wizardForm.values.subscriptionChanged,
        })
    }

    if (subscriptionModalId === null) {
        return null
    }

    return (
        <LemonModal
            isOpen
            onClose={isWizard && !isPickingTarget ? requestWizardCancel : cancel}
            simple={isWizard && !isPickingTarget}
            width={isWizard && !isPickingTarget ? 720 : 650}
            title={isPickingTarget ? 'New subscription' : undefined}
        >
            {isPickingTarget ? (
                <NewSubscriptionTarget aiSubscriptionsAvailable={aiSubscriptionsAvailable} onCancel={cancel} />
            ) : dashboardTargetPending ? (
                <SubscriptionFormSkeleton />
            ) : isWizard ? (
                <SubscriptionWizard
                    insightShortId={insightTarget?.shortId}
                    insightName={insightTarget?.name}
                    dashboard={newSubscriptionDashboard}
                    onCancel={cancel}
                />
            ) : (
                <EditSubscription
                    id={subscriptionModalId}
                    insightShortId={insightTarget?.shortId}
                    dashboard={newSubscriptionDashboard}
                    onCancel={cancel}
                    onDelete={cancel}
                />
            )}
        </LemonModal>
    )
}

import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import type { SubscriptionApi } from 'products/subscriptions/frontend/generated/api.schemas'
import { ResourceTypeEnumApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { SubscriptionAIControls } from './components/SubscriptionAIControls'
import { SubscriptionDeliveryHistory } from './components/SubscriptionDeliveryHistory'
import { isSubscriptionEnabled, subscriptionEditHref, subscriptionName } from './components/SubscriptionsTable'
import { SubscriptionSummary } from './components/SubscriptionSummary'
import { subscriptionSceneLogic } from './subscriptionSceneLogic'
import { subscriptionsSceneLogic } from './subscriptionsSceneLogic'

function SubscriptionDetailActions({ sub }: { sub: SubscriptionApi }): JSX.Element {
    const { push } = useActions(router)
    const { setEnabled, deliverSubscription } = useActions(subscriptionSceneLogic)
    const { subscriptionLoading, deliveringSubscriptionId } = useValues(subscriptionSceneLogic)
    const editHref = subscriptionEditHref(sub)
    const enabled = isSubscriptionEnabled(sub)
    const isDelivering = deliveringSubscriptionId === sub.id

    const deleteSubscription = (): void => {
        const name = subscriptionName(sub)
        void deleteWithUndo({
            endpoint: `projects/${String(getCurrentTeamId())}/subscriptions`,
            object: {
                id: sub.id,
                name,
            },
            callback: () => {
                subscriptionsSceneLogic.findMounted()?.actions.deleteSubscriptionSuccess()
                push(urls.subscriptions())
            },
        })
    }

    return (
        <div className="flex flex-wrap items-center gap-2">
            <LemonTag type={enabled ? 'success' : 'danger'} data-attr="subscription-status-tag">
                {enabled ? 'Enabled' : 'Disabled'}
            </LemonTag>
            <LemonButton
                type="secondary"
                onClick={() => setEnabled({ enabled: !enabled })}
                loading={subscriptionLoading}
                data-attr="subscription-toggle-enabled"
            >
                {enabled ? 'Disable subscription' : 'Enable subscription'}
            </LemonButton>
            {editHref ? (
                <LemonButton type="secondary" onClick={() => push(editHref)}>
                    Edit subscription
                </LemonButton>
            ) : null}
            <LemonButton
                type="primary"
                onClick={() => deliverSubscription(sub.id)}
                loading={isDelivering}
                disabledReason={isDelivering ? 'Sending test delivery…' : null}
                data-attr="subscription-detail-header-test-delivery"
            >
                Test delivery
            </LemonButton>
            <LemonButton
                type="secondary"
                status="danger"
                data-attr="subscription-detail-delete"
                onClick={deleteSubscription}
            >
                Delete
            </LemonButton>
        </div>
    )
}

export function SubscriptionScene(): JSX.Element {
    const {
        subscription,
        subscriptionLoading,
        deliveriesPage,
        deliveriesPageLoading,
        deliveringSubscriptionId,
        deliveryStatusFilter,
        deliveryFeedback,
        recentlyThankedDeliveries,
    } = useValues(subscriptionSceneLogic)
    const { loadDeliveriesPage, deliverSubscription, setDeliveryStatusFilter, submitDeliveryFeedback } =
        useActions(subscriptionSceneLogic)

    const showNotFound = !subscriptionLoading && !subscription

    return (
        <SceneContent>
            {showNotFound ? (
                <NotFound object="subscription" />
            ) : (
                <div className="py-8 flex-1 min-h-0 flex flex-col gap-6 max-w-full">
                    <SceneTitleSection
                        name={subscription ? subscriptionName(subscription) : 'Subscription'}
                        description={null}
                        resourceType={{ type: 'inbox' }}
                        isLoading={subscriptionLoading}
                        actions={subscription ? <SubscriptionDetailActions sub={subscription} /> : undefined}
                    />
                    {subscription ? (
                        // Mute the body when the subscription is paused — the LemonTag in the
                        // header is the explicit signal; this is the at-a-glance reinforcement.
                        <div className={isSubscriptionEnabled(subscription) ? '' : 'opacity-60'}>
                            <SubscriptionSummary sub={subscription} />
                        </div>
                    ) : null}
                    {subscription?.resource_type === ResourceTypeEnumApi.AiPrompt ? <SubscriptionAIControls /> : null}
                    <SubscriptionDeliveryHistory
                        deliveriesPage={deliveriesPage}
                        deliveriesPageLoading={deliveriesPageLoading}
                        loadDeliveriesPage={loadDeliveriesPage}
                        deliveryStatusFilter={deliveryStatusFilter}
                        onDeliveryStatusFilterChange={setDeliveryStatusFilter}
                        // Empty-state CTA intentionally coexists with the header Test delivery button:
                        // it's the discoverable first-run nudge when a subscription has no deliveries yet.
                        onTestDelivery={subscription ? () => deliverSubscription(subscription.id) : undefined}
                        testDeliveryLoading={Boolean(subscription && deliveringSubscriptionId === subscription.id)}
                        onDeliveryFeedback={
                            subscription?.resource_type === ResourceTypeEnumApi.AiPrompt
                                ? (deliveryId, feedback) => submitDeliveryFeedback(deliveryId, feedback, 'in_app')
                                : undefined
                        }
                        deliveryFeedback={deliveryFeedback}
                        recentlyThankedDeliveries={recentlyThankedDeliveries}
                    />
                </div>
            )}
        </SceneContent>
    )
}

export const scene: SceneExport = {
    component: SubscriptionScene,
    logic: subscriptionSceneLogic,
    paramsToProps: ({ params: { subscriptionId } }): { id: string } => ({
        id: String(subscriptionId ?? ''),
    }),
}

import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import {
    subscriptionsDeliveriesList,
    subscriptionsPartialUpdate,
    subscriptionsRetrieve,
    subscriptionsTestDeliveryCreate,
} from 'products/subscriptions/frontend/generated/api'
import type {
    PaginatedSubscriptionDeliveryListApi,
    SubscriptionApi,
    SubscriptionsDeliveriesListStatus,
} from 'products/subscriptions/frontend/generated/api.schemas'

import { runSubscriptionTestDelivery } from '../components/Subscriptions/runSubscriptionTestDelivery'
import { subscriptionName } from './components/SubscriptionsTable'
import type { subscriptionSceneLogicType } from './subscriptionSceneLogicType'

export type SubscriptionSceneLogicProps = {
    id: string
}

export type DeliveryFeedback = 'positive' | 'negative'
export type DeliveryFeedbackSource = 'email' | 'slack' | 'in_app'

export const FEEDBACK_THANKS_DISPLAY_MS = 1000

function parseCursorFromPaginationUrl(url: string | null | undefined): string | undefined {
    if (!url) {
        return undefined
    }
    try {
        const parsed = new URL(url, typeof window !== 'undefined' ? window.location.origin : 'http://localhost')
        const cursor = parsed.searchParams.get('cursor')
        return cursor ?? undefined
    } catch {
        return undefined
    }
}

export const subscriptionSceneLogic = kea<subscriptionSceneLogicType>([
    props({} as SubscriptionSceneLogicProps),
    key(({ id }) => id),
    path((key) => ['scenes', 'subscriptions', 'subscriptionSceneLogic', key]),
    actions({
        deliverSubscription: (id: number) => ({ id }),
        deliverSubscriptionSuccess: true,
        deliverSubscriptionFailure: true,
        setDeliveryStatusFilter: (status: SubscriptionsDeliveriesListStatus | null) => ({ status }),
        submitDeliveryFeedback: (deliveryId: string, feedback: DeliveryFeedback, source: DeliveryFeedbackSource) => ({
            deliveryId,
            feedback,
            source,
        }),
        expireDeliveryThanks: (deliveryId: string) => ({ deliveryId }),
    }),
    reducers({
        deliveringSubscriptionId: [
            null as number | null,
            {
                deliverSubscription: (_, { id }) => id,
                deliverSubscriptionSuccess: () => null,
                deliverSubscriptionFailure: () => null,
            },
        ],
        deliveryStatusFilter: [
            null as SubscriptionsDeliveriesListStatus | null,
            {
                setDeliveryStatusFilter: (_, { status }) => status,
            },
        ],
        deliveryFeedback: [
            {} as Record<string, DeliveryFeedback>,
            // localStorage on purpose: feedback is an analytics event, not a DB row — this only keeps
            // the UI honest (and the capture deduped) across reloads on this browser.
            { persist: true },
            {
                submitDeliveryFeedback: (state, { deliveryId, feedback }) => ({ ...state, [deliveryId]: feedback }),
            },
        ],
        // Transient (not persisted): drives the brief "Thanks!" flash before the row settles
        // into showing the recorded option.
        recentlyThankedDeliveries: [
            {} as Record<string, true>,
            {
                submitDeliveryFeedback: (state, { deliveryId }) => ({ ...state, [deliveryId]: true as const }),
                expireDeliveryThanks: (state, { deliveryId }) => {
                    const { [deliveryId]: _removed, ...rest } = state
                    return rest
                },
            },
        ],
    }),
    loaders(({ values, props }) => ({
        subscription: [
            null as SubscriptionApi | null,
            {
                loadSubscription: async () => {
                    const numericId = parseInt(props.id, 10)
                    if (!Number.isFinite(numericId)) {
                        return null
                    }
                    return await subscriptionsRetrieve(String(getCurrentTeamId()), numericId)
                },
                // Used by the Pause / Resume button on the detail page. PATCH
                // returns the updated subscription so the loader replaces the
                // whole value — no extra GET needed.
                setEnabled: async ({ enabled }: { enabled: boolean }) => {
                    const numericId = parseInt(props.id, 10)
                    if (!Number.isFinite(numericId)) {
                        return values.subscription
                    }
                    return await subscriptionsPartialUpdate(String(getCurrentTeamId()), numericId, { enabled })
                },
            },
        ],
        deliveriesPage: [
            null as PaginatedSubscriptionDeliveryListApi | null,
            {
                loadDeliveriesPage: async (targetUrl: string | null) => {
                    const numericId = parseInt(props.id, 10)
                    if (!Number.isFinite(numericId)) {
                        return null
                    }
                    const teamId = String(getCurrentTeamId())
                    const status = values.deliveryStatusFilter ?? undefined
                    if (targetUrl === null) {
                        return await subscriptionsDeliveriesList(teamId, numericId, status ? { status } : {})
                    }
                    const cursor = parseCursorFromPaginationUrl(targetUrl)
                    return await subscriptionsDeliveriesList(teamId, numericId, {
                        ...(cursor ? { cursor } : {}),
                        ...(status ? { status } : {}),
                    })
                },
            },
        ],
    })),
    selectors({
        breadcrumbs: [
            (s) => [s.subscription],
            (subscription): Breadcrumb[] => {
                const listCrumb: Breadcrumb = {
                    key: Scene.Subscriptions,
                    name: sceneConfigurations[Scene.Subscriptions].name,
                    path: urls.subscriptions(),
                    iconType: sceneConfigurations[Scene.Subscriptions].iconType || 'default_icon_type',
                }
                if (!subscription) {
                    return [listCrumb]
                }
                return [
                    listCrumb,
                    {
                        key: [Scene.Subscription, subscription.id],
                        name: subscriptionName(subscription),
                        iconType: sceneConfigurations[Scene.Subscription].iconType || 'default_icon_type',
                    },
                ]
            },
        ],
    }),
    listeners(({ actions, values, props, cache, selectors }) => ({
        submitDeliveryFeedback: ({ deliveryId, feedback, source }, _breakpoint, _action, previousState) => {
            posthog.capture('ai_report_feedback', {
                subscription_id: parseInt(props.id, 10),
                delivery_id: deliveryId,
                feedback,
                source,
                // Lets analysis distinguish first votes from switches; consumers take the latest
                // event per person + delivery, so a switched vote simply wins.
                previous_feedback: selectors.deliveryFeedback(previousState)[deliveryId] ?? null,
            })
            // In-app thumbs show a per-row "Thanks" state instead of a toast.
            if (source !== 'in_app') {
                lemonToast.success('Thanks for your feedback')
            }
            // Per-delivery key so spamming replaces the previous timer instead of stacking.
            cache.disposables.add(() => {
                const timerId = setTimeout(() => actions.expireDeliveryThanks(deliveryId), FEEDBACK_THANKS_DISPLAY_MS)
                return () => clearTimeout(timerId)
            }, `deliveryThanks-${deliveryId}`)
        },
        setDeliveryStatusFilter: () => {
            if (values.subscription) {
                void actions.loadDeliveriesPage(null)
            }
        },
        loadSubscriptionSuccess: () => {
            if (values.subscription) {
                void actions.loadDeliveriesPage(null)
            }
        },
        deliverSubscription: async ({ id }) => {
            const result = await runSubscriptionTestDelivery(() =>
                subscriptionsTestDeliveryCreate(String(getCurrentTeamId()), id)
            )
            if (result === 'success') {
                actions.deliverSubscriptionSuccess()
            } else {
                actions.deliverSubscriptionFailure()
            }
        },
        // Test delivery returns 202 before Temporal persists the delivery row. Refetch now (fast path) and
        // again after a short delay so the list usually shows the new row without manual refresh.
        deliverSubscriptionSuccess: async (_, breakpoint) => {
            void actions.loadDeliveriesPage(null)
            await breakpoint(2000)
            void actions.loadDeliveriesPage(null)
        },
        loadDeliveriesPageFailure: ({ errorObject }) => {
            const status = errorObject?.status
            const detail = errorObject?.detail
            const message =
                status === 404
                    ? 'Delivery history is not available.'
                    : typeof detail === 'string'
                      ? detail
                      : 'Could not load delivery history.'
            lemonToast.error(message)
        },
        setEnabledSuccess: ({ subscription }) => {
            if (!subscription) {
                return
            }
            lemonToast.success(subscription.enabled ? 'Subscription enabled' : 'Subscription disabled')
        },
        setEnabledFailure: ({ errorObject }) => {
            // Surface the serializer's actionable message (e.g. re-enabling a Slack
            // sub with no integration) — backend already validates this.
            const detail = errorObject?.detail
            lemonToast.error(typeof detail === 'string' ? detail : 'Could not update subscription')
        },
    })),
    urlToAction(({ actions, props, values }) => ({
        // Feedback links in delivered emails/Slack messages land here with these params;
        // capture once, then strip them so a refresh doesn't double-capture.
        [urls.subscription(':id')]: ({ id }, searchParams) => {
            if (id !== props.id) {
                return
            }
            const { feedback_delivery, feedback, feedback_source, ...restSearchParams } = searchParams
            if (!feedback_delivery || (feedback !== 'positive' && feedback !== 'negative')) {
                return
            }
            const deliveryId = String(feedback_delivery)
            if (values.deliveryFeedback[deliveryId]) {
                // Persisted state remembers this delivery — don't re-capture from a re-clicked link.
                lemonToast.info('Your feedback for this report was already recorded')
            } else {
                actions.submitDeliveryFeedback(deliveryId, feedback, feedback_source === 'slack' ? 'slack' : 'email')
            }
            router.actions.replace(router.values.location.pathname, restSearchParams, router.values.hashParams)
        },
    })),
    afterMount(({ actions }) => {
        void actions.loadSubscription()
    }),
])

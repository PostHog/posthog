import { BreakPointFunction, actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { getInsightId } from 'scenes/insights/utils'

import { SubscriptionResourceTypes, SubscriptionType } from '~/types'

import { runSubscriptionTestDelivery } from './runSubscriptionTestDelivery'
import type { subscriptionsLogicType } from './subscriptionsLogicType'
import { toggleSubscriptionEnabled } from './toggleSubscriptionEnabled'
import { SubscriptionsLogicProps } from './utils'

export const subscriptionsLogic = kea<subscriptionsLogicType>([
    path(['lib', 'components', 'Subscriptions', 'subscriptionsLogic']),
    props({} as SubscriptionsLogicProps),
    key(({ insightShortId, dashboardId }) =>
        insightShortId ? `insight-${insightShortId}` : dashboardId ? `dashboard-${dashboardId}` : 'subscriptions'
    ),
    connect({ values: [featureFlagLogic, ['featureFlags']] }),
    actions({
        loadAllSubscriptions: true,
        deleteSubscription: (id: number) => ({ id }),
        deliverSubscription: (id: number) => ({ id }),
        deliverSubscriptionSuccess: true,
        deliverSubscriptionFailure: true,
        setSubscriptionEnabled: (id: number, enabled: boolean) => ({ id, enabled }),
        setSubscriptionEnabledSuccess: true,
        setSubscriptionEnabledFailure: true,
    }),

    loaders(({ props, values }) => ({
        subscriptions: {
            __default: [] as SubscriptionType[],
            loadSubscriptions: async (_?: any, breakpoint?: BreakPointFunction) => {
                if (!props.dashboardId && !props.insightShortId) {
                    return []
                }

                breakpoint?.()

                const insightId = props.insightShortId ? await getInsightId(props.insightShortId) : undefined
                const response = await api.subscriptions.list({
                    dashboardId: props.dashboardId,
                    insightId: insightId,
                })
                breakpoint?.()
                return response.results
            },
        },
        // AI subscriptions are project-scoped (not tied to a specific insight/dashboard), so they're
        // fetched separately and rendered in their own section. Gated behind the AI prompt flag.
        aiSubscriptions: {
            __default: [] as SubscriptionType[],
            loadAiSubscriptions: async (_?: any, breakpoint?: BreakPointFunction) => {
                const inResourceContext = !!props.dashboardId || !!props.insightShortId
                if (!inResourceContext || !values.featureFlags[FEATURE_FLAGS.SUBSCRIPTION_AI_PROMPT]) {
                    return []
                }
                breakpoint?.()
                const response = await api.subscriptions.list({ resourceType: SubscriptionResourceTypes.AiPrompt })
                breakpoint?.()
                return response.results
            },
        },
        // Subscriptions on the dashboard's insight tiles. The backend resolves the tile set from
        // dashboardId, so the count doesn't depend on the dashboard's tiles being loaded client-side.
        insightSubscriptions: {
            __default: [] as SubscriptionType[],
            loadInsightSubscriptions: async (_?: any, breakpoint?: BreakPointFunction) => {
                if (!props.dashboardId) {
                    return []
                }
                breakpoint?.()
                const response = await api.subscriptions.list({ dashboardTiles: props.dashboardId })
                breakpoint?.()
                return response.results
            },
        },
    })),

    reducers({
        subscriptions: {
            deleteSubscription: (state, { id }) => state.filter((a) => a.id !== id),
        },
        aiSubscriptions: {
            deleteSubscription: (state, { id }) => state.filter((a) => a.id !== id),
        },
        insightSubscriptions: {
            deleteSubscription: (state, { id }) => state.filter((a) => a.id !== id),
        },
        deliveringSubscriptionId: [
            null as number | null,
            {
                deliverSubscription: (_, { id }) => id,
                deliverSubscriptionSuccess: () => null,
                deliverSubscriptionFailure: () => null,
            },
        ],
        togglingEnabledId: [
            null as number | null,
            {
                setSubscriptionEnabled: (_, { id }) => id,
                setSubscriptionEnabledSuccess: () => null,
                setSubscriptionEnabledFailure: () => null,
            },
        ],
    }),

    listeners(({ actions }) => ({
        loadAllSubscriptions: () => {
            actions.loadSubscriptions()
            actions.loadAiSubscriptions()
            actions.loadInsightSubscriptions()
        },
        deleteSubscription: async ({ id }) => {
            await deleteWithUndo({
                endpoint: api.subscriptions.determineDeleteEndpoint(),
                object: { name: 'Subscription', id },
                callback: () => {
                    actions.loadAllSubscriptions()
                },
            })
        },
        deliverSubscription: async ({ id }) => {
            const result = await runSubscriptionTestDelivery(() => api.subscriptions.testDelivery(id))
            if (result === 'success') {
                actions.deliverSubscriptionSuccess()
            } else {
                actions.deliverSubscriptionFailure()
            }
        },
        setSubscriptionEnabled: async ({ id, enabled }) => {
            const ok = await toggleSubscriptionEnabled(id, enabled)
            if (ok) {
                actions.setSubscriptionEnabledSuccess()
            } else {
                actions.setSubscriptionEnabledFailure()
            }
        },
        setSubscriptionEnabledSuccess: () => {
            actions.loadAllSubscriptions()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadAllSubscriptions()
    }),
])

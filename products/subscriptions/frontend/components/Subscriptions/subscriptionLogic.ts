import { MakeLogicType, actions, connect, events, kea, key, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'
import type { DeepPartial, DeepPartialMap, FieldName, ValidationErrorType } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { beforeUnload, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import api, { ApiError } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { recordRecentSlackChannel, slackChannelId } from 'lib/integrations/slackChannel'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { objectsEqual } from 'lib/utils/objects'
import { isEmail } from 'lib/utils/url'
import { getInsightId } from 'scenes/insights/utils'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { ExportedAssetType, ExporterFormat, SubscriptionResourceTypes, SubscriptionType } from '~/types'

import {
    subscriptionsDeliveriesList,
    subscriptionsTestDeliveryCreate,
} from 'products/subscriptions/frontend/generated/api'
import type { AIWindowConfigApi, SubscriptionDeliveryApi } from 'products/subscriptions/frontend/generated/api.schemas'

import type { SubscriptionResourceType, UserBasicType, WeekdayType } from '../../../../../frontend/src/types'
import type { OrganizationType, UserType } from '../../../../../frontend/src/types'
import type { AIPromptConfigApi } from '../../generated/api.schemas'
import { runSubscriptionTestDelivery } from './runSubscriptionTestDelivery'
import { SUBSCRIPTION_PREFILL_PARAMS } from './subscriptionNudge'
import { subscriptionsLogic } from './subscriptionsLogic'
import { ALL_DAYS, AI_PROMPT_MAX_LENGTH, SubscriptionBaseProps, urlForSubscription } from './utils'

// Spelled out rather than interpolated, so the event a metric is configured against is greppable.
const EXPORT_NUDGE_CLICKED_EVENTS = {
    dashboard: 'dashboard export nudge clicked',
    insight: 'insight export nudge clicked',
} as const

function validatePrompt(
    resource_type: SubscriptionType['resource_type'],
    prompt: string | null | undefined
): string | undefined {
    if (resource_type !== SubscriptionResourceTypes.AiPrompt) {
        return undefined
    }
    const trimmedPrompt = prompt?.trim()
    if (!trimmedPrompt) {
        return 'A prompt is required for prompt subscriptions'
    }
    if (trimmedPrompt.length > AI_PROMPT_MAX_LENGTH) {
        return `Prompt cannot exceed ${AI_PROMPT_MAX_LENGTH} characters`
    }
    return undefined
}

const AI_WINDOW_MAX_DAYS = 365

function validateAiWindow(subscription: Partial<SubscriptionType>): {
    ai_prompt_config?: { window: { start_days_ago?: any; end_days_ago?: any } }
} {
    if (subscription.resource_type !== SubscriptionResourceTypes.AiPrompt) {
        return {}
    }
    const window = subscription.ai_prompt_config?.window
    const mode = window?.mode ?? 'since_last_sent'
    if (mode === 'since_last_sent') {
        return {}
    }
    const start = window?.start_days_ago
    if (start === null || start === undefined) {
        return { ai_prompt_config: { window: { start_days_ago: 'Set how many days back the report should look' } } }
    }
    if (start < 1 || start > AI_WINDOW_MAX_DAYS) {
        return { ai_prompt_config: { window: { start_days_ago: `Must be between 1 and ${AI_WINDOW_MAX_DAYS} days` } } }
    }
    if (mode === 'last_n_days') {
        return {}
    }
    const end = window?.end_days_ago
    if (end === null || end === undefined) {
        return { ai_prompt_config: { window: { end_days_ago: 'Set where the analyzed range should end' } } }
    }
    if (end < 0 || end > AI_WINDOW_MAX_DAYS) {
        return { ai_prompt_config: { window: { end_days_ago: `Must be between 0 and ${AI_WINDOW_MAX_DAYS} days` } } }
    }
    if (end >= start) {
        return { ai_prompt_config: { window: { end_days_ago: 'Must be closer to now than the start of the range' } } }
    }
    return {}
}

function validateTargetValue(target_type: string, target_value: string | undefined): string | undefined {
    if (!target_value) {
        return target_type === 'email'
            ? 'At least one email is required'
            : target_type === 'slack'
              ? 'A channel is required'
              : 'This field is required.'
    }
    if (target_type === 'email' && !target_value.split(',').every((email) => isEmail(email))) {
        return 'All emails must be valid'
    }
    return undefined
}

function validateDashboardExportInsights(
    subscription: Partial<SubscriptionType>,
    dashboardId: number | undefined
): any {
    if (subscription.resource_type === SubscriptionResourceTypes.AiPrompt || !dashboardId) {
        return undefined
    }
    return subscription.dashboard_export_insights?.length ? undefined : 'Select at least one insight'
}

function validateWeekdaySchedule(subscription: Partial<SubscriptionType>): string | null {
    if (
        (subscription.frequency === 'daily' || subscription.frequency === 'weekly') &&
        !subscription.byweekday?.length
    ) {
        return 'Select at least one delivery day'
    }
    if (
        subscription.frequency !== 'daily' ||
        !subscription.interval ||
        subscription.interval % 7 !== 0 ||
        !subscription.start_date ||
        !subscription.byweekday?.length
    ) {
        return null
    }
    const startWeekday = dayjs.utc(subscription.start_date).format('dddd').toLowerCase()
    return subscription.byweekday.includes(startWeekday as WeekdayType)
        ? null
        : 'Select the delivery day matching the start date for this interval'
}

function validateFrequency(subscription: Partial<SubscriptionType>): string | null {
    if (!subscription.frequency) {
        return 'You need to set a schedule frequency'
    }
    return validateWeekdaySchedule(subscription)
}

function subscriptionSaveErrorMessage(error: unknown): string {
    if (error instanceof ApiError) {
        const msg = (error.detail || error.message || '').trim()
        return msg || 'Could not save subscription. Please try again.'
    }
    if (error instanceof Error && error.message) {
        return error.message
    }
    return 'Could not save subscription. Please try again.'
}

// Frequencies a deep link may prefill. Anything else is ignored rather than trusted into the form.
const FREQUENCY_PREFILL_VALUES: SubscriptionType['frequency'][] = ['daily', 'weekly', 'monthly']

const NEW_SUBSCRIPTION: Partial<SubscriptionType> = {
    resource_type: SubscriptionResourceTypes.Insight,
    frequency: 'weekly',
    interval: 1,
    start_date: dayjs().hour(9).minute(0).second(0).toISOString(),
    target_type: 'email',
    byweekday: ['monday'],
    bysetpos: null,
    dashboard_export_insights: [],
    integration_id: null,
    enabled: true,
    summary_enabled: false,
    summary_prompt_guide: '',
    ai_prompt_config: { window: { mode: 'since_last_sent' } },
    send_test_now: true,
}

export interface SubscriptionLogicProps extends SubscriptionBaseProps {
    id: number | 'new'
    /** Used to build the prefilled title when the form is opened via the subscribe-nudge notification. */
    dashboardName?: string | null
}
// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface subscriptionLogicValues {
    currentOrganization: OrganizationType | null // organizationLogic
    user: UserType | null // userLogic
    isSubscriptionSubmitting: boolean
    isSubscriptionValid: boolean
    lastDelivery: SubscriptionDeliveryApi | null
    lastDeliveryLoadFailed: boolean
    lastDeliveryLoading: boolean
    previewAsset: ExportedAssetType | null
    previewError: string | null
    previewImageUrl: string | null
    previewLoading: boolean
    showSubscriptionErrors: boolean
    subscription: SubscriptionType
    subscriptionAllErrors: Record<string, any>
    subscriptionChanged: boolean
    subscriptionErrors: DeepPartialMap<SubscriptionType, ValidationErrorType>
    subscriptionHasErrors: boolean
    subscriptionLoading: boolean
    subscriptionManualErrors: Record<string, any>
    subscriptionTouched: boolean
    subscriptionTouches: Record<string, boolean>
    subscriptionValidationErrors: DeepPartialMap<SubscriptionType, ValidationErrorType>
    summaryQuota: {
        active_count: number
        at_limit: boolean
        limit: number | null
    } | null
    summaryQuotaLoading: boolean
    testDeliveryLoading: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface subscriptionLogicActions {
    applyDefaultSelectedInsights: (selectedIds: number[]) => {
        selectedIds: number[]
    }
    generatePreview: () => {
        value: true
    }
    loadLastDelivery: () => any
    loadLastDeliveryFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadLastDeliverySuccess: (
        lastDelivery: SubscriptionDeliveryApi | null,
        payload?: any
    ) => {
        lastDelivery: SubscriptionDeliveryApi | null
        payload?: any
    }
    loadSubscription: () => any
    loadSubscriptionFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSubscriptionSuccess: (
        subscription: {
            ai_prompt_config?: AIPromptConfigApi | null | undefined
            bysetpos?: number | null | undefined
            byweekday?: WeekdayType[] | null | undefined
            created_at?: string | undefined
            created_by?: UserBasicType | null | undefined
            dashboard?: number | undefined
            dashboard_export_insights?: number[] | undefined
            deleted?: boolean | undefined
            enabled?: boolean | undefined
            frequency?: 'daily' | 'monthly' | 'weekly' | 'yearly' | undefined
            id?: number | undefined
            insight?: number | undefined
            insight_short_id?: string | null | undefined
            integration_id?: number | null | undefined
            interval?: number | undefined
            next_delivery_date?: string | null | undefined
            prompt?: string | null | undefined
            resource_name?: string | null | undefined
            resource_type?: SubscriptionResourceType | undefined
            send_test_now?: boolean | undefined
            start_date?: string | undefined
            summary?: string | undefined
            summary_enabled?: boolean | undefined
            summary_prompt_guide?: string | undefined
            target_type?: string | undefined
            target_value?: string | undefined
            title?: string | undefined
            until_date?: string | undefined
        },
        payload?: any
    ) => {
        subscription: {
            ai_prompt_config?: AIPromptConfigApi | null | undefined
            bysetpos?: number | null | undefined
            byweekday?: WeekdayType[] | null | undefined
            created_at?: string | undefined
            created_by?: UserBasicType | null | undefined
            dashboard?: number | undefined
            dashboard_export_insights?: number[] | undefined
            deleted?: boolean | undefined
            enabled?: boolean | undefined
            frequency?: 'daily' | 'monthly' | 'weekly' | 'yearly' | undefined
            id?: number | undefined
            insight?: number | undefined
            insight_short_id?: string | null | undefined
            integration_id?: number | null | undefined
            interval?: number | undefined
            next_delivery_date?: string | null | undefined
            prompt?: string | null | undefined
            resource_name?: string | null | undefined
            resource_type?: SubscriptionResourceType | undefined
            send_test_now?: boolean | undefined
            start_date?: string | undefined
            summary?: string | undefined
            summary_enabled?: boolean | undefined
            summary_prompt_guide?: string | undefined
            target_type?: string | undefined
            target_value?: string | undefined
            title?: string | undefined
            until_date?: string | undefined
        }
        payload?: any
    }
    loadSummaryQuota: () => any
    loadSummaryQuotaFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSummaryQuotaSuccess: (
        summaryQuota: {
            active_count: number
            at_limit: boolean
            limit: number | null
        },
        payload?: any
    ) => {
        summaryQuota: {
            active_count: number
            at_limit: boolean
            limit: number | null
        }
        payload?: any
    }
    resetSubscription: (values?: SubscriptionType) => {
        values?: SubscriptionType
    }
    selectAiExamplePrompt: (
        prompt: string,
        label: string,
        window?: AIWindowConfigApi
    ) => {
        label: string
        prompt: string
        window: AIWindowConfigApi | undefined
    }
    sendTestDelivery: () => {
        value: true
    }
    sendTestDeliveryFailure: () => {
        value: true
    }
    sendTestDeliverySuccess: () => {
        value: true
    }
    setPreviewAsset: (asset: ExportedAssetType | null) => {
        asset: ExportedAssetType | null
    }
    setPreviewError: (error: string | null) => {
        error: string | null
    }
    setPreviewImageUrl: (url: string | null) => {
        url: string | null
    }
    setPreviewLoading: (loading: boolean) => {
        loading: boolean
    }
    setSubscriptionManualErrors: (errors: Record<string, any>) => {
        errors: Record<string, any>
    }
    setSubscriptionValue: (
        key: FieldName,
        value: any
    ) => {
        name: FieldName
        value: any
    }
    setSubscriptionValues: (values: DeepPartial<SubscriptionType>) => {
        values: DeepPartial<SubscriptionType>
    }
    submitSubscription: () => {
        value: boolean
    }
    submitSubscriptionFailure: (
        error: Error,
        errors: Record<string, any>
    ) => {
        error: Error
        errors: Record<string, any>
    }
    submitSubscriptionRequest: (subscription: SubscriptionType) => {
        subscription: SubscriptionType
    }
    submitSubscriptionSuccess: (subscription: SubscriptionType) => {
        subscription: SubscriptionType
    }
    touchSubscriptionField: (key: string) => {
        key: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface subscriptionLogicMeta {
    key: string
}

export type subscriptionLogicType = MakeLogicType<
    subscriptionLogicValues,
    subscriptionLogicActions,
    SubscriptionLogicProps,
    subscriptionLogicMeta
>

export const subscriptionLogic = kea<subscriptionLogicType>([
    path(['lib', 'components', 'Subscriptions', 'subscriptionLogic']),
    props({} as SubscriptionLogicProps),
    key(({ id, insightShortId, dashboardId }) => `${insightShortId || dashboardId}-${id ?? 'new'}`),
    connect(() => ({ values: [userLogic, ['user'], organizationLogic, ['currentOrganization']] })),

    actions({
        generatePreview: true,
        sendTestDelivery: true,
        sendTestDeliveryFailure: true,
        sendTestDeliverySuccess: true,
        setPreviewAsset: (asset: ExportedAssetType | null) => ({ asset }),
        setPreviewLoading: (loading: boolean) => ({ loading }),
        setPreviewError: (error: string | null) => ({ error }),
        setPreviewImageUrl: (url: string | null) => ({ url }),
        applyDefaultSelectedInsights: (selectedIds: number[]) => ({ selectedIds }),
        selectAiExamplePrompt: (prompt: string, label: string, window?: AIWindowConfigApi) => ({
            prompt,
            label,
            window,
        }),
    }),

    reducers({
        lastDeliveryLoadFailed: [
            false,
            {
                loadLastDelivery: () => false,
                loadLastDeliveryFailure: () => true,
                loadLastDeliverySuccess: () => false,
            },
        ],
        testDeliveryLoading: [
            false,
            {
                sendTestDelivery: () => true,
                sendTestDeliveryFailure: () => false,
                sendTestDeliverySuccess: () => false,
            },
        ],
        previewAsset: [
            null as ExportedAssetType | null,
            {
                setPreviewAsset: (_, { asset }) => asset,
            },
        ],
        previewLoading: [
            false,
            {
                setPreviewLoading: (_, { loading }) => loading,
            },
        ],
        previewError: [
            null as string | null,
            {
                setPreviewError: (_, { error }) => error,
            },
        ],
        previewImageUrl: [
            null as string | null,
            {
                setPreviewImageUrl: (_, { url }) => url,
            },
        ],
    }),

    loaders(({ props }) => ({
        lastDelivery: {
            __default: null as SubscriptionDeliveryApi | null,
            loadLastDelivery: async () => {
                if (props.id === 'new') {
                    return null
                }
                const deliveries = await subscriptionsDeliveriesList(String(getCurrentTeamId()), props.id)
                return deliveries.results[0] ?? null
            },
        },
        subscription: {
            __default: undefined as unknown as SubscriptionType,
            loadSubscription: async () => {
                if (props.id && props.id !== 'new') {
                    const subscription = await api.subscriptions.get(props.id)
                    // Rows created before a window was chosen carry ai_prompt_config: {} — normalise
                    // so the analysis window select renders the effective default instead of empty.
                    let byweekday = subscription.byweekday
                    if (
                        subscription.frequency === 'daily' &&
                        ((subscription.interval ?? 1) > 1 || !subscription.byweekday?.length)
                    ) {
                        byweekday = [...ALL_DAYS]
                    } else if (!byweekday?.length && subscription.frequency === 'weekly') {
                        byweekday = [dayjs.utc(subscription.start_date).format('dddd').toLowerCase() as WeekdayType]
                    }
                    return {
                        ...subscription,
                        byweekday,
                        // Write-only, so never present on the API response: default the edit form's
                        // "Send a test run now" toggle to on, matching the create flow.
                        send_test_now: true,
                        ai_prompt_config: {
                            ...subscription.ai_prompt_config,
                            window: {
                                ...subscription.ai_prompt_config?.window,
                                mode: subscription.ai_prompt_config?.window?.mode ?? 'since_last_sent',
                            },
                        },
                    }
                }
                return { ...NEW_SUBSCRIPTION }
            },
        },
        summaryQuota: {
            __default: null as { active_count: number; limit: number | null; at_limit: boolean } | null,
            loadSummaryQuota: async () => {
                return await api.subscriptions.summaryQuota()
            },
        },
    })),

    forms(({ props, actions, cache }) => ({
        subscription: {
            defaults: { enabled: NEW_SUBSCRIPTION.enabled } as unknown as SubscriptionType,
            errors: (subscription) => ({
                frequency: validateFrequency(subscription),
                title: !subscription.title ? 'You need to give your subscription a name' : undefined,
                interval: !subscription.interval ? 'You need to set an interval' : undefined,
                start_date: !subscription.start_date ? 'You need to set a delivery time' : undefined,
                target_type: !['slack', 'email'].includes(subscription.target_type)
                    ? 'Unsupported target type'
                    : undefined,
                prompt: validatePrompt(subscription.resource_type, subscription.prompt),
                ...validateAiWindow(subscription),
                target_value: validateTargetValue(subscription.target_type, subscription.target_value),
                dashboard_export_insights: validateDashboardExportInsights(subscription, props.dashboardId),
            }),
            submit: async (subscription, breakpoint) => {
                const isAi = subscription.resource_type === SubscriptionResourceTypes.AiPrompt
                const insightId = !isAi && props.insightShortId ? await getInsightId(props.insightShortId) : undefined

                const payload = {
                    ...subscription,
                    bysetpos: subscription.frequency === 'monthly' ? subscription.bysetpos : null,
                    insight: isAi ? undefined : insightId,
                    dashboard: isAi ? undefined : props.dashboardId,
                    // AI subscriptions have no dashboard, so a carried-over insight selection would
                    // trip the backend's "insights without a dashboard" guard. Clear it.
                    dashboard_export_insights: isAi ? [] : subscription.dashboard_export_insights,
                    // Only AI subscriptions carry a prompt; a stale one on a non-AI sub (e.g. after
                    // toggling resource_type back) would be rejected by the backend, so drop it.
                    prompt: isAi ? subscription.prompt?.trim() : undefined,
                    ai_prompt_config: isAi ? subscription.ai_prompt_config : undefined,
                }

                breakpoint()

                const updatedSub: SubscriptionType =
                    props.id === 'new'
                        ? await api.subscriptions.create(payload)
                        : await api.subscriptions.update(props.id, payload)

                actions.resetSubscription()

                if (updatedSub.id !== props.id) {
                    router.actions.replace(urlForSubscription(updatedSub.id, props))
                    posthog.capture('subscription created', {
                        resource_type: isAi ? 'ai' : props.dashboardId ? 'dashboard' : 'insight',
                        dashboard_id: props.dashboardId,
                        insight_short_id: props.insightShortId,
                        subscription_id: updatedSub.id,
                        target_type: updatedSub.target_type,
                        ai_summary_prefilled: cache.prefillBaseline?.summary_enabled === true,
                    })
                }

                // If a subscriptionsLogic for this insight/dashboard is mounted already, refresh both
                // its resource-scoped list and the AI subscriptions section so new entries show up
                const mountedSubscriptionsLogic = subscriptionsLogic.findMounted(props)
                mountedSubscriptionsLogic?.actions.loadAllSubscriptions()
                actions.loadSubscriptionSuccess(updatedSub)
                actions.loadSummaryQuota()
                lemonToast.success(`Subscription saved.`)

                return updatedSub
            },
        },
    })),

    listeners(({ actions, values, props, selectors, cache }) => ({
        loadSubscriptionSuccess: () => {
            if (props.id !== 'new') {
                actions.loadLastDelivery()
            }
        },
        sendTestDelivery: async () => {
            if (props.id === 'new') {
                actions.sendTestDeliveryFailure()
                return
            }
            const subscriptionId = props.id
            const result = await runSubscriptionTestDelivery(() =>
                subscriptionsTestDeliveryCreate(String(getCurrentTeamId()), subscriptionId)
            )
            if (result === 'success') {
                actions.sendTestDeliverySuccess()
                return
            }
            actions.sendTestDeliveryFailure()
        },
        sendTestDeliverySuccess: async (_, breakpoint) => {
            await breakpoint(2000)
            actions.loadLastDelivery()
        },
        submitSubscriptionSuccess: ({ subscription }) => {
            if (subscription?.target_type === 'slack' && subscription.target_value && subscription.integration_id) {
                recordRecentSlackChannel(subscription.integration_id, slackChannelId(subscription.target_value))
            }
        },
        applyDefaultSelectedInsights: ({ selectedIds }) => {
            if (cache.prefillBaseline) {
                // Prefilled form: the auto-selection joins the programmatic baseline. A reset here
                // would wipe the "changed" flag the prefill deliberately set (disabling Create), so
                // set the value instead and fold the ids into the baseline, keeping the untouched-form
                // navigation suppression matching.
                actions.setSubscriptionValue('dashboard_export_insights', selectedIds)
                cache.prefillBaseline = { ...cache.prefillBaseline, dashboard_export_insights: selectedIds }
                return
            }
            // Reset the form's "changed" state after auto-selecting defaults so it doesn't trip the
            // unsaved-changes warning; merge the IDs into the subscription to preserve them.
            actions.resetSubscription({ ...values.subscription, dashboard_export_insights: selectedIds })
        },
        loadSummaryQuotaSuccess: ({ summaryQuota }) => {
            // Nudge upsell, deferred until the quota answer exists: default the AI summary on for a
            // nudge-prefilled create. Never for a non-consented org (the server rejects the create
            // and the consent popover must not appear uninvited) and never at the quota limit —
            // both gates mirror the server-side create validation. Applied at most once, so a
            // user toggling it back off is respected on later quota reloads.
            if (
                props.id !== 'new' ||
                !cache.prefillBaseline ||
                cache.prefillBaseline.summary_enabled === true ||
                summaryQuota?.at_limit ||
                !values.currentOrganization?.is_ai_data_processing_approved ||
                values.subscription?.summary_enabled
            ) {
                return
            }
            actions.setSubscriptionValue('summary_enabled', true)
            // Folding the default into the baseline both keeps the untouched-form navigation
            // suppression matching and serves as the applied-once guard on later quota reloads.
            cache.prefillBaseline = { ...cache.prefillBaseline, summary_enabled: true }
        },
        selectAiExamplePrompt: ({ prompt, label, window }) => {
            posthog.capture('subscription_ai_example_prompt_selected', { label })
            actions.setSubscriptionValue('prompt', prompt)
            const currentMode = values.subscription?.ai_prompt_config?.window?.mode ?? 'since_last_sent'
            if (window && currentMode === 'since_last_sent') {
                // Presets that imply a timeframe prefill the analysis window — but only while the
                // window is still the default, so a deliberately-chosen one survives the click.
                // Spread keeps future sibling config keys intact.
                actions.setSubscriptionValues({
                    ai_prompt_config: { ...values.subscription?.ai_prompt_config, window },
                })
            }
        },
        submitSubscriptionFailure: ({ error }) => {
            // Kea-forms emits this when client validation fails; fields already show errors.
            if (error instanceof Error && error.message === 'Validation Failed') {
                return
            }
            const message = subscriptionSaveErrorMessage(error)
            if (error instanceof ApiError && error.attr) {
                actions.setSubscriptionManualErrors({ [error.attr]: message })
            }
            lemonToast.error(message)
        },

        setSubscriptionValue: ({ name, value }, _breakpoint, _action, previousState) => {
            const key = Array.isArray(name) ? name[0] : name
            if (key === 'frequency') {
                if (value === 'daily') {
                    actions.setSubscriptionValues({
                        bysetpos: null,
                        byweekday: ALL_DAYS.slice(0, 5),
                    })
                } else if (value === 'weekly') {
                    actions.setSubscriptionValues({
                        bysetpos: null,
                        byweekday: ['monday'],
                    })
                } else if (value === 'monthly') {
                    actions.setSubscriptionValues({
                        bysetpos: 1,
                        byweekday: ['monday'],
                    })
                } else {
                    actions.setSubscriptionValues({
                        bysetpos: null,
                        byweekday: null,
                    })
                }
            }

            if (key === 'interval' && values.subscription.frequency === 'daily' && value > 1) {
                actions.setSubscriptionValue('byweekday', [...ALL_DAYS])
            }

            if (key === 'target_type') {
                actions.setSubscriptionValues({
                    target_value: '',
                    integration_id: null,
                })
            }

            const path = Array.isArray(name) ? name.join('.') : name
            if (path === 'ai_prompt_config.window.mode') {
                // Reducers run before listeners, so previousState tells a real mode switch (reset the
                // day bounds) apart from a same-mode re-select (keep them).
                const previousConfig = selectors.subscription(previousState)?.ai_prompt_config
                if (value !== previousConfig?.window?.mode) {
                    actions.setSubscriptionValues({
                        ai_prompt_config: { ...previousConfig, window: { mode: value } },
                    })
                }
            }
        },

        generatePreview: async (_, breakpoint) => {
            const subscription = values.subscription
            if (!subscription) {
                return
            }

            actions.setPreviewLoading(true)
            actions.setPreviewError(null)
            if (values.previewImageUrl) {
                URL.revokeObjectURL(values.previewImageUrl)
            }
            actions.setPreviewImageUrl(null)

            try {
                const insightId =
                    subscription.insight ??
                    (props.insightShortId ? await getInsightId(props.insightShortId) : undefined)
                const dashboardId = subscription.dashboard ?? props.dashboardId

                const exportData: Partial<ExportedAssetType> = {
                    export_format: ExporterFormat.PNG,
                    ...(insightId ? { insight: insightId } : {}),
                    ...(dashboardId ? { dashboard: dashboardId } : {}),
                    export_context: {
                        path: '',
                    },
                }

                const asset = await api.exports.create(exportData)
                breakpoint()

                if (asset.has_content) {
                    actions.setPreviewAsset(asset)
                    await fetchPreviewImage(asset, actions)
                } else if (asset.exception) {
                    actions.setPreviewError(asset.exception)
                } else {
                    const maxAttempts = 30
                    for (let i = 0; i < maxAttempts; i++) {
                        await new Promise((resolve) => setTimeout(resolve, 3000))
                        breakpoint()

                        const updated = await api.exports.get(asset.id)
                        if (updated.has_content) {
                            actions.setPreviewAsset(updated)
                            await fetchPreviewImage(updated, actions)
                            return
                        }
                        if (updated.exception) {
                            actions.setPreviewError(updated.exception)
                            return
                        }
                    }
                    actions.setPreviewError('Preview generation timed out. Please try again.')
                }
            } catch (e) {
                breakpoint()
                actions.setPreviewError(e instanceof Error ? e.message : 'Failed to generate preview')
            } finally {
                actions.setPreviewLoading(false)
            }
        },
    })),

    events(({ actions, values }) => ({
        afterMount: () => {
            // Load the org-wide AI summary quota once per logic mount so
            // the paywall conditional in EditSubscription has data to react
            // to without depending on URL navigation. urlToAction kept its
            // own loader call in case the user navigates between :id and
            // /new without unmounting; afterMount covers initial mount and
            // Storybook (which doesn't navigate the route).
            actions.loadSummaryQuota()
        },
        beforeUnmount: () => {
            if (values.previewImageUrl) {
                URL.revokeObjectURL(values.previewImageUrl)
            }
        },
    })),

    beforeUnload(({ actions, values, cache }) => ({
        // A form whose only "changes" are the programmatic prefill was never touched by the user —
        // navigating away from it must not prompt to discard. Any real edit diverges from the
        // captured baseline and re-arms the prompt.
        enabled: () =>
            values.subscriptionChanged &&
            !(cache.prefillBaseline && objectsEqual(values.subscription, cache.prefillBaseline)),
        message: 'Changes you made will be discarded.',
        onConfirm: () => {
            actions.resetSubscription()
        },
    })),

    urlToAction(({ actions, props, cache, values }) => ({
        '/*/*/subscriptions/new': (_, searchParams) => {
            actions.loadSubscriptionSuccess({ ...NEW_SUBSCRIPTION })
            if (searchParams.resource_type === SubscriptionResourceTypes.AiPrompt) {
                actions.setSubscriptionValue('resource_type', SubscriptionResourceTypes.AiPrompt)
            }
            const nudgeSubject = props.dashboardId ? 'dashboard' : props.insightShortId ? 'insight' : null
            // The route pattern matches any subject's page, so without this a logic keyed to another
            // insight or dashboard prefills and reports the click for someone else's nudge.
            const isOwnSubject =
                removeProjectIdIfPresent(router.values.location.pathname) ===
                urlForSubscription('new', { dashboardId: props.dashboardId, insightShortId: props.insightShortId })
            if (
                searchParams[SUBSCRIPTION_PREFILL_PARAMS.param] === SUBSCRIPTION_PREFILL_PARAMS.nudge &&
                nudgeSubject &&
                isOwnSubject
            ) {
                // Consume the params before applying: the replace synchronously re-enters this
                // handler (resetting the form to plain defaults), and it also makes a later refresh
                // of the URL neither re-capture the click nor re-apply a stale prefill.
                const {
                    [SUBSCRIPTION_PREFILL_PARAMS.param]: _prefill,
                    [SUBSCRIPTION_PREFILL_PARAMS.viaParam]: _via,
                    ...restSearchParams
                } = router.values.searchParams
                router.actions.replace(router.values.location.pathname, restSearchParams, router.values.hashParams)
                const prefill: Partial<SubscriptionType> = {
                    // Only dashboards reach this route with a name in hand, so an insight's
                    // subscription is named for the schedule rather than for the insight.
                    title:
                        nudgeSubject === 'dashboard'
                            ? `${props.dashboardName || 'Dashboard'} weekly digest`
                            : 'Weekly digest',
                    ...(values.user?.email ? { target_value: values.user.email } : {}),
                }
                // Goes through setSubscriptionValues (not the loaded baseline) so the form is marked
                // dirty immediately — the prefilled fields are a deliberate change, not the pristine
                // default, so "Create subscription" doesn't require an extra no-op edit to enable.
                actions.setSubscriptionValues(prefill)
                cache.prefillBaseline = { ...NEW_SUBSCRIPTION, ...prefill }
                const via = searchParams[SUBSCRIPTION_PREFILL_PARAMS.viaParam]
                posthog.capture(
                    via === SUBSCRIPTION_PREFILL_PARAMS.viaExport
                        ? EXPORT_NUDGE_CLICKED_EVENTS[nudgeSubject]
                        : 'dashboard subscribe nudge clicked',
                    {
                        kind: nudgeSubject,
                        ...(nudgeSubject === 'dashboard'
                            ? { dashboard_id: props.dashboardId }
                            : { insight_short_id: props.insightShortId }),
                        prefilled: !!values.user?.email,
                        via: via ?? SUBSCRIPTION_PREFILL_PARAMS.viaNotification,
                    }
                )
            }
            if (searchParams.target_type) {
                actions.setSubscriptionValue('target_type', searchParams.target_type)
            }
        },
        '/*/*/subscriptions/:id': () => {
            actions.loadSubscription()
        },
        '/subscriptions/new': (_, searchParams) => {
            actions.loadSubscriptionSuccess({ ...NEW_SUBSCRIPTION, resource_type: SubscriptionResourceTypes.AiPrompt })
            if (searchParams.target_type) {
                actions.setSubscriptionValue('target_type', searchParams.target_type)
            }
            // Products link here with a ready-made report (e.g. the MCP analytics recurring-report
            // cards) so the user picks a destination instead of writing a prompt. Set through
            // setSubscriptionValues so the form starts dirty — the prefill is a deliberate change,
            // not a pristine default, so "Create" doesn't need a no-op edit first.
            const prefill: Partial<SubscriptionType> = {}
            if (typeof searchParams.prompt === 'string' && searchParams.prompt) {
                prefill.prompt = searchParams.prompt.slice(0, AI_PROMPT_MAX_LENGTH)
            }
            if (typeof searchParams.title === 'string' && searchParams.title) {
                prefill.title = searchParams.title
            }
            if (FREQUENCY_PREFILL_VALUES.includes(searchParams.frequency)) {
                prefill.frequency = searchParams.frequency
            }
            if (Object.keys(prefill).length > 0) {
                actions.setSubscriptionValues(prefill)
            }
        },
        '/subscriptions/:id/edit': () => {
            actions.loadSubscription()
        },
    })),
])

async function fetchPreviewImage(
    asset: ExportedAssetType,
    actions: { setPreviewImageUrl: (url: string | null) => void; setPreviewError: (error: string | null) => void }
): Promise<void> {
    const url = api.exports.determineExportUrl(asset.id)
    const response = await fetch(url, { credentials: 'include' })
    if (!response.ok) {
        actions.setPreviewError('Failed to load preview image')
        return
    }
    const blob = await response.blob()
    const objectUrl = URL.createObjectURL(blob)
    actions.setPreviewImageUrl(objectUrl)
}

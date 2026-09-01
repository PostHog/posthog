import { MakeLogicType, actions, connect, events, kea, key, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'
import type { DeepPartial, DeepPartialMap, FieldName, ValidationErrorType } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { beforeUnload, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import api, { ApiError } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { recordRecentSlackChannel, slackChannelId } from 'lib/integrations/slackChannel'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { objectsEqual } from 'lib/utils/objects'
import { isEmail } from 'lib/utils/url'
import { getInsightId } from 'scenes/insights/utils'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { ExportedAssetType, ExporterFormat, SubscriptionResourceTypes, SubscriptionType } from '~/types'

import {
    subscriptionsCreate,
    subscriptionsDeliveriesList,
    subscriptionsPartialUpdate,
    subscriptionsPulseConfigurationOptionsList,
    subscriptionsRetrieve,
    subscriptionsTestDeliveryCreate,
} from 'products/subscriptions/frontend/generated/api'
import type {
    AIWindowConfigApi,
    AIWindowConfigModeEnumApi,
    ProactiveConfigurationOptionsApi,
    ProactiveSubscriptionConfigApi,
    RepositoryOptionApi,
    SubscriptionApi,
    SubscriptionContextApi,
    SubscriptionDeliveryApi,
    SubscriptionWriteApi,
    SubscriptionWriteApiContextsItem,
} from 'products/subscriptions/frontend/generated/api.schemas'

import type { FeatureFlagsSet } from '../../../../../frontend/src/lib/logic/featureFlagLogic'
import type { WeekdayType } from '../../../../../frontend/src/types'
import type { OrganizationType, UserType } from '../../../../../frontend/src/types'
import type { SubscriptionResourceType, UserBasicType } from '../../../../../frontend/src/types'
import type { AIPromptConfigApi } from '../../generated/api.schemas'
import { runSubscriptionTestDelivery } from './runSubscriptionTestDelivery'
import {
    normalizeSubscriptionEditTab,
    normalizeSubscriptionWizardStep,
    shouldShowSubscriptionActions,
    subscriptionEditTabForErrors,
    subscriptionWizardStepForErrors,
} from './subscriptionFormNavigation'
import type { SubscriptionEditTab, SubscriptionWizardStep } from './subscriptionFormNavigation'
import { SUBSCRIPTION_PREFILL_PARAMS } from './subscriptionNudge'
import { subscriptionsLogic } from './subscriptionsLogic'
import { ALL_DAYS, AI_PROMPT_MAX_LENGTH, MAX_CONTEXTS, SubscriptionBaseProps, urlForSubscription } from './utils'

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

function validateProactiveConfig(subscription: SubscriptionFormType): {
    proactive_config?: { repository?: string }
} {
    if (subscription.resource_type !== SubscriptionResourceTypes.AiPrompt) {
        return {}
    }
    const config = subscription.proactive_config
    if (config?.enabled && config.create_draft_pr && !config.repository?.trim()) {
        return { proactive_config: { repository: 'Select a repository for automatic draft pull requests' } }
    }
    if (config?.enabled && config.create_draft_pr && !config.repository_integration_id) {
        return {
            proactive_config: {
                repository: 'Select the GitHub connection that authorizes this repository',
            },
        }
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

export type SubscriptionFormType = SubscriptionType &
    Omit<SubscriptionApi, keyof SubscriptionType | 'contexts'> & { contexts: SubscriptionContextApi[] }

type SubscriptionWritePayload = Omit<Parameters<typeof subscriptionsCreate>[1], 'proactive_config'> & {
    proactive_config?: Omit<ProactiveSubscriptionConfigApi, 'repository_grant_id'>
}

const DEFAULT_PROACTIVE_CONFIG: ProactiveSubscriptionConfigApi = {
    enabled: false,
    public_research_enabled: true,
    repository: null,
    repository_integration_id: null,
    create_draft_pr: false,
    repository_grant_id: null,
}

function proactiveConfigForWrite(
    config: ProactiveSubscriptionConfigApi
): Omit<ProactiveSubscriptionConfigApi, 'repository_grant_id'> {
    const { repository_grant_id: _repositoryGrantId, ...writeConfig } = config
    return writeConfig
}

function subscriptionForForm(subscription: SubscriptionApi): SubscriptionFormType {
    return {
        ...subscription,
        ai_prompt_config: subscription.ai_prompt_config ?? undefined,
        bysetpos: subscription.bysetpos ?? null,
        byweekday: subscription.byweekday ?? null,
        created_by: subscription.created_by as unknown as UserBasicType,
        dashboard: subscription.dashboard ?? undefined,
        insight: subscription.insight ?? undefined,
        title: subscription.title ?? '',
        until_date: subscription.until_date ?? undefined,
        contexts: [...(subscription.contexts ?? [])],
        proactive_config: subscription.proactive_config ?? { ...DEFAULT_PROACTIVE_CONFIG },
    }
}

function contextKey(context: SubscriptionContextApi): string {
    return 'dashboard_id' in context ? `dashboard:${context.dashboard_id}` : `insight:${context.insight_id}`
}

function contextForWrite(context: SubscriptionContextApi): SubscriptionWriteApiContextsItem {
    return 'dashboard_id' in context ? { dashboard_id: context.dashboard_id } : { insight_id: context.insight_id }
}

const NEW_SUBSCRIPTION = {
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
    proactive_config: { ...DEFAULT_PROACTIVE_CONFIG },
    contexts: [],
    send_test_now: true,
} as unknown as SubscriptionFormType

export interface SubscriptionLogicProps extends SubscriptionBaseProps {
    id: number | 'new'
    /** Used to build the prefilled title when the form is opened via the subscribe-nudge notification. */
    dashboardName?: string | null
    insightName?: string
    creationSource?: 'editor' | 'wizard'
}
// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface subscriptionLogicValues {
    featureFlags: FeatureFlagsSet // featureFlagLogic
    receivedFeatureFlags: boolean // featureFlagLogic
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
    proactiveConfigurationOptions: ProactiveConfigurationOptionsApi | null
    proactiveConfigurationOptionsLoadFailed: boolean
    proactiveConfigurationOptionsLoading: boolean
    showSubscriptionErrors: boolean
    subscription: SubscriptionFormType
    subscriptionAllErrors: Record<string, any>
    subscriptionChanged: boolean
    subscriptionEditTab: SubscriptionEditTab
    subscriptionErrors: DeepPartialMap<SubscriptionFormType, ValidationErrorType>
    subscriptionHasErrors: boolean
    subscriptionInitialized: boolean
    subscriptionLoading: boolean
    subscriptionManualErrors: Record<string, any>
    subscriptionTouched: boolean
    subscriptionTouches: Record<string, boolean>
    subscriptionValidationErrors: DeepPartialMap<SubscriptionFormType, ValidationErrorType>
    subscriptionWizardStep: SubscriptionWizardStep
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
    setFeatureFlags: (
        flags: string[],
        variants: Record<string, boolean | string>
    ) => {
        flags: string[]
        variants: Record<string, boolean | string>
    } // featureFlagLogic
    addContext: (context: SubscriptionContextApi) => {
        context: SubscriptionContextApi
    }
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
    loadProactiveConfigurationOptions: () => any
    loadProactiveConfigurationOptionsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadProactiveConfigurationOptionsSuccess: (
        proactiveConfigurationOptions: ProactiveConfigurationOptionsApi,
        payload?: any
    ) => {
        proactiveConfigurationOptions: ProactiveConfigurationOptionsApi
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
            bysetpos: number | null
            byweekday: WeekdayType[] | null
            contexts: SubscriptionContextApi[]
            count?: number | null | undefined
            created_at: string
            created_by?: UserBasicType | null | undefined
            dashboard?: number | undefined
            dashboard_export_insights?: number[] | undefined
            deleted?: boolean | undefined
            enabled?: boolean | undefined
            frequency: 'daily' | 'monthly' | 'weekly' | 'yearly'
            id: number
            insight?: number | undefined
            insight_short_id?: string | null | undefined
            integration_id?: number | null | undefined
            interval: number
            invite_message?: string | null | undefined
            next_delivery_date: string | null
            proactive_config: ProactiveSubscriptionConfigApi
            prompt?: string | null | undefined
            resource_name?: string | null | undefined
            resource_type: SubscriptionResourceType
            send_test_now?: boolean | undefined
            start_date: string
            summary: string
            summary_enabled?: boolean | undefined
            summary_prompt_guide?: string | undefined
            target_type: string
            target_value: string
            title: string
            until_date?: string | undefined
        },
        payload?: any
    ) => {
        subscription: {
            ai_prompt_config?: AIPromptConfigApi | null | undefined
            bysetpos: number | null
            byweekday: WeekdayType[] | null
            contexts: SubscriptionContextApi[]
            count?: number | null | undefined
            created_at: string
            created_by?: UserBasicType | null | undefined
            dashboard?: number | undefined
            dashboard_export_insights?: number[] | undefined
            deleted?: boolean | undefined
            enabled?: boolean | undefined
            frequency: 'daily' | 'monthly' | 'weekly' | 'yearly'
            id: number
            insight?: number | undefined
            insight_short_id?: string | null | undefined
            integration_id?: number | null | undefined
            interval: number
            invite_message?: string | null | undefined
            next_delivery_date: string | null
            proactive_config: ProactiveSubscriptionConfigApi
            prompt?: string | null | undefined
            resource_name?: string | null | undefined
            resource_type: SubscriptionResourceType
            send_test_now?: boolean | undefined
            start_date: string
            summary: string
            summary_enabled?: boolean | undefined
            summary_prompt_guide?: string | undefined
            target_type: string
            target_value: string
            title: string
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
    prefillCurrentContext: () => {
        value: true
    }
    removeContext: (context: SubscriptionContextApi) => {
        context: SubscriptionContextApi
    }
    resetSubscription: (values?: SubscriptionFormType) => {
        values?: SubscriptionFormType
    }
    selectAiAnalysisWindow: (mode: AIWindowConfigApi['mode']) => {
        mode: AIWindowConfigModeEnumApi | undefined
    }
    selectAiExamplePrompt: (
        prompt: string,
        label: string
    ) => {
        label: string
        prompt: string
    }
    selectProactiveRepository: (repository: RepositoryOptionApi | null) => {
        repository: RepositoryOptionApi | null
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
    setDraftPrEnabled: (enabled: boolean) => {
        enabled: boolean
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
    setProactiveEnabled: (enabled: boolean) => {
        enabled: boolean
    }
    setPublicResearchEnabled: (enabled: boolean) => {
        enabled: boolean
    }
    setSubscriptionEditTab: (tab: SubscriptionEditTab) => {
        tab: SubscriptionEditTab
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
    setSubscriptionValues: (values: DeepPartial<SubscriptionFormType>) => {
        values: DeepPartial<SubscriptionFormType>
    }
    setSubscriptionWizardStep: (step: SubscriptionWizardStep) => {
        step: SubscriptionWizardStep
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
    submitSubscriptionRequest: (subscription: SubscriptionFormType) => {
        subscription: SubscriptionFormType
    }
    submitSubscriptionSuccess: (subscription: SubscriptionFormType) => {
        subscription: SubscriptionFormType
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
    key(
        ({ id, insightShortId, dashboardId, creationSource }) =>
            `${insightShortId || dashboardId}-${id ?? 'new'}-${creationSource ?? 'editor'}`
    ),
    connect(() => ({
        actions: [featureFlagLogic, ['setFeatureFlags']],
        values: [
            userLogic,
            ['user'],
            organizationLogic,
            ['currentOrganization'],
            featureFlagLogic,
            ['featureFlags', 'receivedFeatureFlags'],
        ],
    })),

    actions({
        addContext: (context: SubscriptionContextApi) => ({ context }),
        generatePreview: true,
        prefillCurrentContext: true,
        removeContext: (context: SubscriptionContextApi) => ({ context }),
        sendTestDelivery: true,
        sendTestDeliveryFailure: true,
        sendTestDeliverySuccess: true,
        setPreviewAsset: (asset: ExportedAssetType | null) => ({ asset }),
        setPreviewLoading: (loading: boolean) => ({ loading }),
        setPreviewError: (error: string | null) => ({ error }),
        setPreviewImageUrl: (url: string | null) => ({ url }),
        applyDefaultSelectedInsights: (selectedIds: number[]) => ({ selectedIds }),
        selectAiExamplePrompt: (prompt: string, label: string) => ({
            prompt,
            label,
        }),
        selectAiAnalysisWindow: (mode: AIWindowConfigApi['mode']) => ({ mode }),
        selectProactiveRepository: (repository: RepositoryOptionApi | null) => ({ repository }),
        setDraftPrEnabled: (enabled: boolean) => ({ enabled }),
        setProactiveEnabled: (enabled: boolean) => ({ enabled }),
        setPublicResearchEnabled: (enabled: boolean) => ({ enabled }),
        setSubscriptionEditTab: (tab: SubscriptionEditTab) => ({ tab }),
        setSubscriptionWizardStep: (step: SubscriptionWizardStep) => ({ step }),
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
        proactiveConfigurationOptionsLoadFailed: [
            false,
            {
                loadProactiveConfigurationOptions: () => false,
                loadProactiveConfigurationOptionsFailure: () => true,
                loadProactiveConfigurationOptionsSuccess: () => false,
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
        subscriptionInitialized: [
            false,
            {
                loadSubscriptionSuccess: () => true,
            },
        ],
        subscriptionEditTab: [
            'content' as SubscriptionEditTab,
            {
                setSubscriptionEditTab: (_, { tab }) => tab,
            },
        ],
        subscriptionWizardStep: [
            'report' as SubscriptionWizardStep,
            {
                setSubscriptionWizardStep: (_, { step }) => step,
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
            __default: undefined as unknown as SubscriptionFormType,
            loadSubscription: async () => {
                if (props.id && props.id !== 'new') {
                    const subscription = subscriptionForForm(
                        await subscriptionsRetrieve(String(getCurrentTeamId()), props.id)
                    )
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
                        contexts: subscription.contexts,
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
        proactiveConfigurationOptions: {
            __default: null as ProactiveConfigurationOptionsApi | null,
            loadProactiveConfigurationOptions: async () =>
                await subscriptionsPulseConfigurationOptionsList(String(getCurrentTeamId())),
        },
    })),

    forms(({ props, actions, cache, values }) => ({
        subscription: {
            defaults: { enabled: NEW_SUBSCRIPTION.enabled, contexts: [] } as unknown as SubscriptionFormType,
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
                ...validateProactiveConfig(subscription),
                target_value: validateTargetValue(subscription.target_type, subscription.target_value),
                dashboard_export_insights: validateDashboardExportInsights(subscription, props.dashboardId),
            }),
            submit: async (subscription, breakpoint) => {
                const prefilledContext = await (cache.contextPrefillPromise as
                    | Promise<SubscriptionContextApi | null>
                    | undefined)
                const currentSubscription =
                    prefilledContext &&
                    !subscription.contexts.some(
                        (selectedContext) => contextKey(selectedContext) === contextKey(prefilledContext)
                    )
                        ? { ...subscription, contexts: [...subscription.contexts, prefilledContext] }
                        : subscription
                const isAi = currentSubscription.resource_type === SubscriptionResourceTypes.AiPrompt
                const insightId = !isAi && props.insightShortId ? await getInsightId(props.insightShortId) : undefined

                const payload: SubscriptionWritePayload = {
                    dashboard: isAi ? undefined : props.dashboardId,
                    insight: isAi ? undefined : insightId,
                    // AI subscriptions have no dashboard, so a carried-over insight selection would
                    // trip the backend's "insights without a dashboard" guard. Clear it.
                    dashboard_export_insights: isAi ? [] : currentSubscription.dashboard_export_insights,
                    // Only AI subscriptions carry a prompt; a stale one on a non-AI sub (e.g. after
                    // toggling resource_type back) would be rejected by the backend, so drop it.
                    prompt: isAi ? currentSubscription.prompt?.trim() : undefined,
                    ai_prompt_config: isAi ? (currentSubscription.ai_prompt_config ?? undefined) : undefined,
                    proactive_config: isAi ? proactiveConfigForWrite(currentSubscription.proactive_config) : undefined,
                    contexts:
                        isAi && values.featureFlags[FEATURE_FLAGS.SUBSCRIPTION_AI_CONTEXTS]
                            ? currentSubscription.contexts.map(contextForWrite)
                            : undefined,
                    target_type: currentSubscription.target_type as SubscriptionWriteApi['target_type'],
                    target_value: currentSubscription.target_value,
                    frequency: currentSubscription.frequency,
                    interval: currentSubscription.interval,
                    byweekday: currentSubscription.byweekday,
                    bysetpos: currentSubscription.frequency === 'monthly' ? currentSubscription.bysetpos : null,
                    count: currentSubscription.count,
                    start_date: currentSubscription.start_date,
                    until_date: currentSubscription.until_date,
                    deleted: currentSubscription.deleted,
                    enabled: currentSubscription.enabled,
                    title: currentSubscription.title,
                    integration_id: currentSubscription.integration_id,
                    invite_message: currentSubscription.invite_message,
                    send_test_now: currentSubscription.send_test_now,
                    summary_enabled: currentSubscription.summary_enabled,
                    summary_prompt_guide: currentSubscription.summary_prompt_guide,
                }

                breakpoint()

                const updatedSub = subscriptionForForm(
                    props.id === 'new'
                        ? await subscriptionsCreate(
                              String(getCurrentTeamId()),
                              payload as Parameters<typeof subscriptionsCreate>[1]
                          )
                        : await subscriptionsPartialUpdate(
                              String(getCurrentTeamId()),
                              props.id,
                              payload as Parameters<typeof subscriptionsPartialUpdate>[2]
                          )
                )

                actions.resetSubscription()

                if (updatedSub.id !== props.id) {
                    router.actions.replace(urlForSubscription(updatedSub.id, props))
                    posthog.capture('subscription created', {
                        creation_source: props.creationSource ?? 'editor',
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
            const initialSubscription = values.subscription
            if (!initialSubscription) {
                return
            }
            const showActions = shouldShowSubscriptionActions({
                subscription: initialSubscription,
                proactiveConfigurationOptions: values.proactiveConfigurationOptions,
                proactiveConfigurationOptionsLoading: values.proactiveConfigurationOptionsLoading,
                proactiveConfigurationOptionsLoadFailed: values.proactiveConfigurationOptionsLoadFailed,
            })
            actions.setSubscriptionWizardStep(
                normalizeSubscriptionWizardStep(values.subscriptionWizardStep, showActions)
            )
            actions.setSubscriptionEditTab(normalizeSubscriptionEditTab(values.subscriptionEditTab, showActions))
            const defaults = { ...initialSubscription }
            let defaultsApplied = false
            if (
                props.id === 'new' &&
                defaults.target_type === 'email' &&
                !defaults.target_value &&
                values.user?.email
            ) {
                defaults.target_value = values.user.email
                defaultsApplied = true
            }
            if (props.id === 'new' && props.creationSource === 'wizard' && !defaults.title) {
                let title = 'Weekly report'
                if (props.dashboardName) {
                    title = `${props.dashboardName} weekly digest`
                } else if (props.insightName) {
                    title = `Weekly report: ${props.insightName}`
                }
                defaults.title = title
                defaultsApplied = true
            }
            if (defaultsApplied) {
                actions.resetSubscription(defaults)
            }
            if (props.id !== 'new') {
                actions.loadLastDelivery()
            } else if (initialSubscription.resource_type === SubscriptionResourceTypes.AiPrompt) {
                actions.prefillCurrentContext()
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
        addContext: ({ context }) => {
            const contexts = values.subscription.contexts ?? []
            if (contexts.some((selectedContext) => contextKey(selectedContext) === contextKey(context))) {
                return
            }
            if (contexts.length >= MAX_CONTEXTS) {
                return
            }
            actions.setSubscriptionValue('contexts', [...contexts, context])
        },
        removeContext: ({ context }) => {
            actions.setSubscriptionValue(
                'contexts',
                (values.subscription.contexts ?? []).filter(
                    (selectedContext) => contextKey(selectedContext) !== contextKey(context)
                )
            )
        },
        prefillCurrentContext: async () => {
            if (props.id !== 'new' || values.subscription.resource_type !== SubscriptionResourceTypes.AiPrompt) {
                return
            }
            if (!values.receivedFeatureFlags) {
                cache.contextPrefillWaitingForFeatureFlags = true
                return
            }
            if (!values.featureFlags[FEATURE_FLAGS.SUBSCRIPTION_AI_CONTEXTS]) {
                return
            }
            if (props.dashboardId) {
                actions.addContext({
                    dashboard_id: props.dashboardId,
                    dashboard_name: props.dashboardName || 'Untitled dashboard',
                })
                return
            }
            if (!props.insightShortId) {
                return
            }
            const prefillPromise = getInsightId(props.insightShortId)
                .then((insightId): SubscriptionContextApi | null => {
                    if (
                        !insightId ||
                        props.id !== 'new' ||
                        values.subscription.resource_type !== SubscriptionResourceTypes.AiPrompt
                    ) {
                        return null
                    }
                    const context: SubscriptionContextApi = {
                        insight_id: insightId,
                        insight_short_id: props.insightShortId!,
                        insight_name: props.insightName || 'Untitled insight',
                    }
                    actions.addContext(context)
                    return context
                })
                .catch((): null => {
                    lemonToast.error(
                        'Could not add this insight as report context. Select it again, or continue with project data.'
                    )
                    return null
                })
            cache.contextPrefillPromise = prefillPromise
            try {
                await prefillPromise
            } finally {
                if (cache.contextPrefillPromise === prefillPromise) {
                    cache.contextPrefillPromise = undefined
                }
            }
        },
        setFeatureFlags: () => {
            if (!cache.contextPrefillWaitingForFeatureFlags) {
                return
            }
            cache.contextPrefillWaitingForFeatureFlags = false
            actions.prefillCurrentContext()
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
        selectAiExamplePrompt: ({ prompt, label }) => {
            posthog.capture('subscription_ai_example_prompt_selected', { label })
            actions.setSubscriptionValue('prompt', prompt)
        },
        selectAiAnalysisWindow: ({ mode }) => {
            const config = values.subscription?.ai_prompt_config ?? {}
            const window = { ...config.window, mode }
            if (mode === 'last_n_days' && !window.start_days_ago) {
                window.start_days_ago = 7
            }
            if (mode === 'days_ago_range') {
                if (window.start_days_ago === null || window.start_days_ago === undefined) {
                    window.start_days_ago = 14
                }
                if (window.end_days_ago === null || window.end_days_ago === undefined) {
                    window.end_days_ago = 0
                }
            }
            actions.setSubscriptionValues({ ai_prompt_config: { ...config, window } })
        },
        setProactiveEnabled: ({ enabled }) => {
            const config = values.subscription.proactive_config ?? DEFAULT_PROACTIVE_CONFIG
            actions.setSubscriptionValues({
                proactive_config: enabled
                    ? { ...config, enabled: true }
                    : {
                          ...DEFAULT_PROACTIVE_CONFIG,
                          repository_grant_id: config.repository_grant_id ?? null,
                          public_research_enabled: config.public_research_enabled,
                      },
            })
            if (
                !enabled &&
                values.proactiveConfigurationOptions?.proactive_available !== true &&
                !values.proactiveConfigurationOptionsLoading &&
                !values.proactiveConfigurationOptionsLoadFailed
            ) {
                actions.setSubscriptionWizardStep(normalizeSubscriptionWizardStep(values.subscriptionWizardStep, false))
                actions.setSubscriptionEditTab(normalizeSubscriptionEditTab(values.subscriptionEditTab, false))
            }
        },
        setDraftPrEnabled: ({ enabled }) => {
            const config = values.subscription.proactive_config ?? DEFAULT_PROACTIVE_CONFIG
            actions.setSubscriptionValues({
                proactive_config: enabled
                    ? { ...config, create_draft_pr: true }
                    : {
                          ...config,
                          create_draft_pr: false,
                          repository: null,
                          repository_integration_id: null,
                      },
            })
        },
        selectProactiveRepository: ({ repository }) => {
            const config = values.subscription.proactive_config ?? DEFAULT_PROACTIVE_CONFIG
            actions.setSubscriptionValues({
                proactive_config: {
                    ...config,
                    repository: repository?.repository ?? null,
                    repository_integration_id: repository?.repository_integration_id ?? null,
                },
            })
        },
        setPublicResearchEnabled: ({ enabled }) => {
            const config = values.subscription.proactive_config ?? DEFAULT_PROACTIVE_CONFIG
            actions.setSubscriptionValues({
                proactive_config: { ...config, public_research_enabled: enabled },
            })
        },
        submitSubscriptionFailure: ({ error, errors }) => {
            // Kea-forms emits this when client validation fails; fields already show errors.
            if (error instanceof Error && error.message === 'Validation Failed') {
                const showActions = shouldShowSubscriptionActions({
                    subscription: values.subscription,
                    proactiveConfigurationOptions: values.proactiveConfigurationOptions,
                    proactiveConfigurationOptionsLoading: values.proactiveConfigurationOptionsLoading,
                    proactiveConfigurationOptionsLoadFailed: values.proactiveConfigurationOptionsLoadFailed,
                })
                if (props.creationSource === 'wizard') {
                    const invalidStep = subscriptionWizardStepForErrors(
                        errors ?? values.subscriptionAllErrors,
                        showActions
                    )
                    if (invalidStep) {
                        actions.setSubscriptionWizardStep(invalidStep)
                    }
                } else {
                    const invalidTab = subscriptionEditTabForErrors(errors ?? values.subscriptionAllErrors, showActions)
                    if (invalidTab) {
                        actions.setSubscriptionEditTab(invalidTab)
                    }
                }
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
            if (key === 'resource_type' && value === SubscriptionResourceTypes.AiPrompt) {
                actions.prefillCurrentContext()
            }
            if (key === 'resource_type' && value !== SubscriptionResourceTypes.AiPrompt) {
                actions.setSubscriptionWizardStep(normalizeSubscriptionWizardStep(values.subscriptionWizardStep, false))
                actions.setSubscriptionEditTab(normalizeSubscriptionEditTab(values.subscriptionEditTab, false))
            }
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
                    target_value: value === 'email' ? (values.user?.email ?? '') : '',
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
        setSubscriptionValues: ({ values: updatedValues }) => {
            if (updatedValues.resource_type === SubscriptionResourceTypes.AiPrompt) {
                actions.prefillCurrentContext()
            }
        },

        loadProactiveConfigurationOptionsSuccess: () => {
            const showActions = shouldShowSubscriptionActions({
                subscription: values.subscription,
                proactiveConfigurationOptions: values.proactiveConfigurationOptions,
                proactiveConfigurationOptionsLoading: values.proactiveConfigurationOptionsLoading,
                proactiveConfigurationOptionsLoadFailed: values.proactiveConfigurationOptionsLoadFailed,
            })
            actions.setSubscriptionWizardStep(
                normalizeSubscriptionWizardStep(values.subscriptionWizardStep, showActions)
            )
            actions.setSubscriptionEditTab(normalizeSubscriptionEditTab(values.subscriptionEditTab, showActions))
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

    events(({ actions, values, props }) => ({
        afterMount: () => {
            if (props.id === 'new' && !values.subscriptionInitialized) {
                actions.loadSubscriptionSuccess({ ...NEW_SUBSCRIPTION })
            }
            // Load the org-wide AI summary quota once per logic mount so
            // the paywall conditional in EditSubscription has data to react
            // to without depending on URL navigation. urlToAction kept its
            // own loader call in case the user navigates between :id and
            // /new without unmounting; afterMount covers initial mount and
            // Storybook (which doesn't navigate the route).
            actions.loadSummaryQuota()
            actions.loadProactiveConfigurationOptions()
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

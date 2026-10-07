import { MakeLogicType, actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { objectsEqual } from 'lib/utils/objects'
import { projectLogic } from 'scenes/projectLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { AnyPropertyFilter, Breadcrumb, IntegrationType, ResourceEditedEvent, TeamPublicType, TeamType } from '~/types'

import { resourceEditedLogic } from 'products/notifications/frontend/resourceEditedLogic'
import {
    hogFlowsBatchJobsCancelCreate,
    hogFlowsBatchJobsCreate,
    hogFlowsBatchJobsList,
    hogFlowsCreate,
    hogFlowsPartialUpdate,
    hogFlowsRetrieve,
    hogFlowsSchedulesCreate,
    hogFlowsSchedulesDestroy,
    hogFlowsUserBlastRadiusCreate,
} from 'products/workflows/frontend/generated/api'
import type {
    BlastRadiusApi,
    HogFlowApi,
    HogFlowBatchJobApi,
    HogFlowConversionApi,
    HogFlowEmailSendingRateLimitApi,
    HogFlowScheduleApi,
} from 'products/workflows/frontend/generated/api.schemas'

import {
    DEFAULT_STATE,
    ONE_TIME_RRULE,
    ScheduleState,
    buildSummary,
    isOneTimeSchedule,
    parseRRuleToState,
    stateToRRule,
} from '../Workflows/hogflows/steps/components/rrule-helpers'
import type { UtmTagValues } from '../Workflows/hogflows/steps/components/UtmTagFields'
import { ResourceSaveQueue } from '../Workflows/resourceSaveQueue'
import {
    AUDIENCE_PREFILL_PARAM,
    type BroadcastPrefill,
    NAME_PREFILL_PARAM,
    parseBroadcastAudiencePrefill,
    SOURCE_PREFILL_PARAM,
} from './broadcastAudiencePrefill'
import { confirmArchiveBroadcast, confirmDeleteBroadcast, restoreBroadcast } from './broadcastLifecycle'
import {
    BroadcastStatus,
    StoppableBroadcast,
    canEditInWizard,
    canMoveToDraft,
    getBroadcastStatus,
} from './broadcastsLogic'
import {
    COMPOSER_DRAFT_PARAM,
    COMPOSER_DRAFT_VALUE,
    advanceAgentDraft,
    broadcastPath,
    editedFields,
    loadComposerDraft,
    saveComposerDraft,
    snapshotBroadcast,
} from './broadcastUsage'

export type BroadcastWizardStep = 'recipients' | 'goal' | 'content' | 'schedule' | 'review'

const EMAIL_AUTOSAVE_RETRIES = 3
const EMAIL_AUTOSAVE_RETRY_MS = 2000

export const BROADCAST_WIZARD_STEPS: BroadcastWizardStep[] = ['recipients', 'goal', 'content', 'schedule', 'review']

// Shown in the stepper, and named to PostHog AI so it points the user at the step they can see.
export const BROADCAST_WIZARD_STEP_LABELS: Record<BroadcastWizardStep, string> = {
    recipients: 'Recipients',
    goal: 'Goal',
    content: 'Content',
    schedule: 'Schedule',
    review: 'Review',
}

export type BroadcastScheduleMode = 'now' | 'later' | 'recurring'

// The value stored in the email action's `inputs.email.value`, mirroring the
// `template-email` hog function template's default input shape.
export interface BroadcastEmailValue {
    to: { email: string; name?: string }
    from: { integrationId?: number | null; integrationIds?: number[] }
    replyTo?: string
    cc?: string
    bcc?: string
    subject: string
    preheader?: string
    text: string
    html: string
    design: Record<string, any> | null
}

export const DEFAULT_BROADCAST_EMAIL: BroadcastEmailValue = {
    to: { email: '{{ person.properties.email }}', name: '' },
    from: {},
    replyTo: '',
    cc: '',
    bcc: '',
    subject: '',
    preheader: '',
    text: '',
    html: '',
    design: null,
}

/** Settings on the email step that the email content itself does not carry. */
export interface BroadcastEmailSettings {
    /** The opt-out category. People who opted out of it are skipped. */
    messageCategoryId: string | null
    messageCategoryType: string | null
    trackingEnabled: boolean
    utmTagsEnabled: boolean
    utmParams: UtmTagValues
}

export const DEFAULT_BROADCAST_EMAIL_SETTINGS: BroadcastEmailSettings = {
    messageCategoryId: null,
    messageCategoryType: null,
    trackingEnabled: true,
    utmTagsEnabled: false,
    utmParams: {},
}

function readEmailSettings(broadcast: HogFlowApi): BroadcastEmailSettings | null {
    const config = findAction(broadcast, 'function_email')?.config
    if (!config) {
        return null
    }
    return {
        messageCategoryId: config.message_category_id ?? null,
        messageCategoryType: config.message_category_type ?? null,
        trackingEnabled: config.tracking_enabled !== false,
        utmTagsEnabled: config.utm_tags_enabled === true,
        utmParams: config.utm_params ?? {},
    }
}

function emailSettingsConfig(settings: BroadcastEmailSettings | undefined): Record<string, any> {
    if (!settings) {
        return {}
    }
    return {
        message_category_id: settings.messageCategoryId ?? undefined,
        message_category_type: settings.messageCategoryType ?? undefined,
        tracking_enabled: settings.trackingEnabled,
        utm_tags_enabled: settings.utmTagsEnabled,
        utm_params: settings.utmParams,
    }
}

export const DEFAULT_BROADCAST_CONVERSION: HogFlowConversionApi = {
    events: [],
    filters: [],
    window: '7d',
}

// pinned: action node ids referenced by saved broadcasts — renaming breaks resume of existing drafts
const TRIGGER_ACTION_ID = 'trigger_node'
export const EMAIL_ACTION_ID = 'email_node'
const EXIT_ACTION_ID = 'exit_node'

function findAction(broadcast: HogFlowApi, type: string): Record<string, any> | undefined {
    const flowActions = (broadcast.actions ?? []) as unknown as Record<string, any>[]
    return flowActions.find((action) => action.type === type)
}

function readAudience(broadcast: HogFlowApi): AnyPropertyFilter[] | undefined {
    return findAction(broadcast, 'trigger')?.config?.filters?.properties as AnyPropertyFilter[] | undefined
}

// Compares two server copies, so derived keys the server adds (such as bytecode) match on both sides.
// A field the other edit changed must follow the saved copy, or the next save sends the stale value back
// under a fresh base and overwrites that edit without a conflict. A field it did not change keeps the
// local value, so an unsaved local edit (a rename, an audience change) is not lost.
function changedElsewhere<T>(latest: HogFlowApi, base: HogFlowApi | null, read: (broadcast: HogFlowApi) => T): boolean {
    return !base || !objectsEqual(read(latest), read(base))
}

export type BroadcastSummaryTab = 'overview' | 'content' | 'runs'

export interface BroadcastWizardLogicProps {
    id: string // 'new' for new broadcasts, or a UUID for editing/viewing
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface broadcastWizardLogicValues {
    integrations: IntegrationType[] | null // integrationsLogic
    integrationsLoading: boolean // integrationsLogic
    currentProjectId: number | null // projectLogic
    currentTeam: TeamPublicType | TeamType | null // teamLogic
    audienceProperties: AnyPropertyFilter[]
    batchJobs: HogFlowBatchJobApi[]
    batchJobsLoading: boolean
    blastRadius: BlastRadiusApi | null
    blastRadiusLoading: boolean
    breadcrumbs: Breadcrumb[]
    broadcast: HogFlowApi | null
    broadcastAsWorkflow: HogFlowApi | null
    broadcastId: string | null
    broadcastLoading: boolean
    canEditContent: boolean
    canMoveToDraft: boolean
    conversion: HogFlowConversionApi
    currentStep: BroadcastWizardStep
    currentStepHasErrors: boolean
    duplicating: boolean
    effectiveTimezone: string
    email: BroadcastEmailValue
    emailRateLimit: HogFlowEmailSendingRateLimitApi | null
    emailSettings: BroadcastEmailSettings
    entrySource: string | null
    expandedRunIds: string[]
    expandedRunOverride: string[] | null
    firstInvalidStep: BroadcastWizardStep | null
    goalEnabled: boolean
    hasHydrated: boolean
    hasLoadedBatchJobs: boolean
    isReadOnly: boolean
    launching: boolean
    movingToDraft: boolean
    name: string
    rateLimitedSendDuration: string
    recurringRepeating: boolean
    recurringStartsAt: string | null
    saving: boolean
    scheduleMode: BroadcastScheduleMode
    scheduleState: ScheduleState
    scheduleSummary: string
    scheduleTimezone: string | null
    selectedSender: IntegrationType | null
    sendAt: string | null
    stepValidationErrors: Record<BroadcastWizardStep, string[]>
    summaryStatus: BroadcastStatus
    summaryTab: BroadcastSummaryTab
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface broadcastWizardLogicActions {
    resourceEdited: (event: ResourceEditedEvent) => {
        event: ResourceEditedEvent
    } // resourceEditedLogic
    applyExternalEdit: (
        broadcast: HogFlowApi,
        base: HogFlowApi | null
    ) => {
        base: HogFlowApi | null
        broadcast: HogFlowApi
    }
    archiveBroadcast: () => {
        value: true
    }
    collapseRun: (runId: string) => {
        runId: string
    }
    continueStep: () => {
        value: true
    }
    deleteBroadcast: () => {
        value: true
    }
    draftAutosaved: (broadcast: HogFlowApi) => {
        broadcast: HogFlowApi
    }
    duplicateBroadcast: () => {
        value: true
    }
    duplicateBroadcastFinished: () => {
        value: true
    }
    ensureDraft: () => {
        value: true
    }
    expandRun: (runId: string) => {
        runId: string
    }
    hydrateFromBroadcast: (broadcast: HogFlowApi) => {
        broadcast: HogFlowApi
    }
    launchBroadcast: () => {
        value: true
    }
    launchBroadcastFinished: () => {
        value: true
    }
    loadBatchJobs: () => any
    loadBatchJobsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadBatchJobsSuccess: (
        batchJobs: HogFlowBatchJobApi[],
        payload?: any
    ) => {
        batchJobs: HogFlowBatchJobApi[]
        payload?: any
    }
    loadBlastRadius: () => any
    loadBlastRadiusFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadBlastRadiusSuccess: (
        blastRadius: BlastRadiusApi | null,
        payload?: any
    ) => {
        blastRadius: BlastRadiusApi | null
        payload?: any
    }
    loadBroadcast: () => any
    loadBroadcastFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadBroadcastSuccess: (
        broadcast: HogFlowApi | null,
        payload?: any
    ) => {
        broadcast: HogFlowApi | null
        payload?: any
    }
    loadExternalEdit: () => {
        value: true
    }
    moveToDraft: () => {
        value: true
    }
    moveToDraftFinished: () => {
        value: true
    }
    nextStep: () => {
        value: true
    }
    prefillFromLink: (prefill: BroadcastPrefill) => {
        prefill: BroadcastPrefill
    }
    prevStep: () => {
        value: true
    }
    replayDeferredEdit: () => {
        value: true
    }
    reportReviewVisit: () => {
        value: true
    }
    restoreBroadcast: () => {
        value: true
    }
    saveBroadcastFinished: (broadcast: HogFlowApi | null) => {
        broadcast: HogFlowApi | null
    }
    saveName: () => {
        value: true
    }
    setAudienceProperties: (properties: AnyPropertyFilter[]) => {
        properties: AnyPropertyFilter[]
    }
    setConversion: (conversion: HogFlowConversionApi) => {
        conversion: HogFlowConversionApi
    }
    setEmail: (email: BroadcastEmailValue) => {
        email: BroadcastEmailValue
    }
    setEmailRateLimit: (emailRateLimit: HogFlowEmailSendingRateLimitApi | null) => {
        emailRateLimit: HogFlowEmailSendingRateLimitApi | null
    }
    setEmailSettings: (settings: Partial<BroadcastEmailSettings>) => {
        settings: Partial<BroadcastEmailSettings>
    }
    setExpandedRunOverride: (runIds: string[]) => {
        runIds: string[]
    }
    setGoalEnabled: (enabled: boolean) => {
        enabled: boolean
    }
    setName: (name: string) => {
        name: string
    }
    setRecurringRepeating: (repeating: boolean) => {
        repeating: boolean
    }
    setRecurringStartsAt: (startsAt: string | null) => {
        startsAt: string | null
    }
    setRecurringStartsAtFromPicker: (pickerDate: string | null) => {
        pickerDate: string | null
    }
    setScheduleMode: (mode: BroadcastScheduleMode) => {
        mode: BroadcastScheduleMode
    }
    setScheduleState: (
        state: ScheduleState,
        source?: 'natural_language' | 'picker'
    ) => {
        source: 'natural_language' | 'picker'
        state: ScheduleState
    }
    setScheduleTimezone: (
        timezone: string,
        previousTimezone?: string
    ) => {
        previousTimezone: string | undefined
        timezone: string
    }
    setSendAt: (sendAt: string | null) => {
        sendAt: string | null
    }
    setSendAtFromPicker: (pickerDate: string | null) => {
        pickerDate: string | null
    }
    setStep: (step: BroadcastWizardStep) => {
        step: BroadcastWizardStep
    }
    setSummaryTab: (tab: BroadcastSummaryTab) => {
        tab: BroadcastSummaryTab
    }
    showSavedDraftUrl: () => {
        value: true
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface broadcastWizardLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        broadcastAsWorkflow: (
            broadcast: HogFlowApi | null,
            name: string,
            audienceProperties: AnyPropertyFilter[],
            goalEnabled: boolean,
            conversion: HogFlowConversionApi,
            email: BroadcastEmailValue,
            emailRateLimit: HogFlowEmailSendingRateLimitApi | null,
            emailSettings: BroadcastEmailSettings
        ) => HogFlowApi | null
        broadcastId: (broadcast: HogFlowApi | null, id: string) => string | null
        expandedRunIds: (expandedRunOverride: string[] | null, batchJobs: HogFlowBatchJobApi[]) => string[]
        canMoveToDraft: (
            broadcast: HogFlowApi | null,
            batchJobs: HogFlowBatchJobApi[],
            hasLoadedBatchJobs: boolean
        ) => boolean
        canEditContent: (broadcast: HogFlowApi | null) => boolean
        summaryStatus: (
            broadcast: HogFlowApi | null,
            batchJobs: HogFlowBatchJobApi[],
            hasLoadedBatchJobs: boolean
        ) => BroadcastStatus
        isReadOnly: (broadcast: HogFlowApi | null) => boolean
        effectiveTimezone: (scheduleTimezone: string | null, currentTeam: TeamPublicType | TeamType | null) => string
        selectedSender: (email: BroadcastEmailValue, integrations: IntegrationType[] | null) => IntegrationType | null
        stepValidationErrors: (
            goalEnabled: boolean,
            conversion: HogFlowConversionApi,
            email: BroadcastEmailValue,
            scheduleMode: BroadcastScheduleMode,
            sendAt: string | null,
            recurringStartsAt: string | null,
            integrations: IntegrationType[] | null,
            integrationsLoading: boolean
        ) => Record<BroadcastWizardStep, string[]>
        currentStepHasErrors: (
            stepValidationErrors: Record<BroadcastWizardStep, string[]>,
            currentStep: BroadcastWizardStep
        ) => boolean
        firstInvalidStep: (stepValidationErrors: Record<BroadcastWizardStep, string[]>) => BroadcastWizardStep | null
        scheduleSummary: (
            scheduleMode: BroadcastScheduleMode,
            sendAt: string | null,
            scheduleState: ScheduleState,
            recurringStartsAt: string | null,
            recurringRepeating: boolean,
            effectiveTimezone: string
        ) => string
        rateLimitedSendDuration: (
            emailRateLimit: HogFlowEmailSendingRateLimitApi | null,
            blastRadius: BlastRadiusApi | null
        ) => string
        breadcrumbs: (name: string) => Breadcrumb[]
    }
}

export type broadcastWizardLogicType = MakeLogicType<
    broadcastWizardLogicValues,
    broadcastWizardLogicActions,
    BroadcastWizardLogicProps,
    broadcastWizardLogicMeta
>

export const broadcastWizardLogic = kea<broadcastWizardLogicType>([
    path(['products', 'workflows', 'frontend', 'Broadcasts', 'broadcastWizardLogic']),
    props({} as BroadcastWizardLogicProps),
    key((props) => props.id),

    connect(() => ({
        values: [
            projectLogic,
            ['currentProjectId'],
            teamLogic,
            ['currentTeam'],
            integrationsLogic,
            ['integrations', 'integrationsLoading'],
        ],
        actions: [resourceEditedLogic, ['resourceEdited']],
    })),

    actions({
        setStep: (step: BroadcastWizardStep) => ({ step }),
        nextStep: true,
        prevStep: true,
        continueStep: true,
        reportReviewVisit: true,
        setName: (name: string) => ({ name }),
        prefillFromLink: (prefill: BroadcastPrefill) => ({ prefill }),
        saveName: true,
        setAudienceProperties: (properties: AnyPropertyFilter[]) => ({ properties }),
        setGoalEnabled: (enabled: boolean) => ({ enabled }),
        setConversion: (conversion: HogFlowConversionApi) => ({ conversion }),
        setEmailRateLimit: (emailRateLimit: HogFlowEmailSendingRateLimitApi | null) => ({ emailRateLimit }),
        setEmailSettings: (settings: Partial<BroadcastEmailSettings>) => ({ settings }),
        setEmail: (email: BroadcastEmailValue) => ({ email }),
        setScheduleMode: (mode: BroadcastScheduleMode) => ({ mode }),
        setSendAt: (sendAt: string | null) => ({ sendAt }),
        setSendAtFromPicker: (pickerDate: string | null) => ({ pickerDate }),
        setScheduleState: (state: ScheduleState, source: 'picker' | 'natural_language' = 'picker') => ({
            state,
            source,
        }),
        setRecurringStartsAt: (startsAt: string | null) => ({ startsAt }),
        setRecurringStartsAtFromPicker: (pickerDate: string | null) => ({ pickerDate }),
        setScheduleTimezone: (timezone: string, previousTimezone?: string) => ({ timezone, previousTimezone }),
        setRecurringRepeating: (repeating: boolean) => ({ repeating }),
        hydrateFromBroadcast: (broadcast: HogFlowApi) => ({ broadcast }),
        saveBroadcastFinished: (broadcast: HogFlowApi | null) => ({ broadcast }),
        ensureDraft: true,
        showSavedDraftUrl: true,
        draftAutosaved: (broadcast: HogFlowApi) => ({ broadcast }),
        applyExternalEdit: (broadcast: HogFlowApi, base: HogFlowApi | null) => ({ broadcast, base }),
        replayDeferredEdit: true,
        loadExternalEdit: true,
        expandRun: (runId: string) => ({ runId }),
        collapseRun: (runId: string) => ({ runId }),
        setExpandedRunOverride: (runIds: string[]) => ({ runIds }),
        setSummaryTab: (tab: BroadcastSummaryTab) => ({ tab }),
        launchBroadcast: true,
        launchBroadcastFinished: true,
        moveToDraft: true,
        moveToDraftFinished: true,
        duplicateBroadcast: true,
        archiveBroadcast: true,
        restoreBroadcast: true,
        deleteBroadcast: true,
        duplicateBroadcastFinished: true,
    }),

    loaders(({ props, values }) => ({
        broadcast: [
            null as HogFlowApi | null,
            {
                loadBroadcast: async () => {
                    if (props.id === 'new' || !values.currentProjectId) {
                        return values.broadcast
                    }
                    return await hogFlowsRetrieve(String(values.currentProjectId), props.id)
                },
            },
        ],
        blastRadius: [
            null as BlastRadiusApi | null,
            {
                loadBlastRadius: async () => {
                    if (!values.currentProjectId) {
                        return null
                    }
                    return await hogFlowsUserBlastRadiusCreate(String(values.currentProjectId), {
                        filters: { properties: values.audienceProperties },
                        dedupe_key: 'email',
                    })
                },
            },
        ],
        batchJobs: [
            [] as HogFlowBatchJobApi[],
            {
                loadBatchJobs: async () => {
                    if (!values.broadcastId || !values.currentProjectId) {
                        return []
                    }
                    return await hogFlowsBatchJobsList(String(values.currentProjectId), values.broadcastId)
                },
            },
        ],
    })),

    reducers(({ props }) => ({
        broadcast: {
            saveBroadcastFinished: (state: HogFlowApi | null, { broadcast }: { broadcast: HogFlowApi | null }) =>
                broadcast ?? state,
            draftAutosaved: (_, { broadcast }) => broadcast,
            applyExternalEdit: (_, { broadcast }) => broadcast,
        },
        // Null until the sender expands or collapses a run; until then the latest run shows open.
        summaryTab: [
            'overview' as BroadcastSummaryTab,
            {
                setSummaryTab: (_, { tab }) => tab,
            },
        ],
        expandedRunOverride: [
            null as string[] | null,
            {
                setExpandedRunOverride: (_, { runIds }) => runIds,
            },
        ],
        currentStep: [
            'recipients' as BroadcastWizardStep,
            {
                setStep: (_, { step }) => step,
                nextStep: (state) => {
                    const index = BROADCAST_WIZARD_STEPS.indexOf(state)
                    return BROADCAST_WIZARD_STEPS[Math.min(index + 1, BROADCAST_WIZARD_STEPS.length - 1)]
                },
                prevStep: (state) => {
                    const index = BROADCAST_WIZARD_STEPS.indexOf(state)
                    return BROADCAST_WIZARD_STEPS[Math.max(index - 1, 0)]
                },
            },
        ],
        name: [
            'New broadcast',
            {
                setName: (_, { name }) => name,
                prefillFromLink: (state, { prefill }) => prefill.name || state,
                hydrateFromBroadcast: (state, { broadcast }) => broadcast.name || state,
                applyExternalEdit: (state, { broadcast, base }) =>
                    changedElsewhere(broadcast, base, (b) => b.name) ? broadcast.name || state : state,
            },
        ],
        // Kept for the launch event, so a launch counts toward the product it started from.
        entrySource: [
            null as string | null,
            {
                prefillFromLink: (_, { prefill }) => prefill.source ?? null,
            },
        ],
        audienceProperties: [
            [] as AnyPropertyFilter[],
            {
                setAudienceProperties: (_, { properties }) => properties,
                prefillFromLink: (_, { prefill }) => prefill.properties,
                hydrateFromBroadcast: (state, { broadcast }) => {
                    const trigger = findAction(broadcast, 'trigger')
                    return (trigger?.config?.filters?.properties as AnyPropertyFilter[]) ?? state
                },
                applyExternalEdit: (state, { broadcast, base }) =>
                    changedElsewhere(broadcast, base, readAudience) ? (readAudience(broadcast) ?? state) : state,
            },
        ],
        goalEnabled: [
            false,
            {
                setGoalEnabled: (_, { enabled }) => enabled,
                hydrateFromBroadcast: (state, { broadcast }) => {
                    const conversion = broadcast.conversion
                    if (!conversion) {
                        return state
                    }
                    return (conversion.events?.length ?? 0) > 0 || (conversion.filters?.length ?? 0) > 0
                },
                applyExternalEdit: (state, { broadcast, base }) =>
                    changedElsewhere(broadcast, base, (b) => b.conversion)
                        ? (broadcast.conversion?.events?.length ?? 0) > 0 ||
                          (broadcast.conversion?.filters?.length ?? 0) > 0
                        : state,
            },
        ],
        conversion: [
            DEFAULT_BROADCAST_CONVERSION,
            {
                setConversion: (_, { conversion }) => conversion,
                hydrateFromBroadcast: (state, { broadcast }) =>
                    broadcast.conversion ? { ...DEFAULT_BROADCAST_CONVERSION, ...broadcast.conversion } : state,
                applyExternalEdit: (state, { broadcast, base }) =>
                    changedElsewhere(broadcast, base, (b) => b.conversion) && broadcast.conversion
                        ? { ...DEFAULT_BROADCAST_CONVERSION, ...broadcast.conversion }
                        : state,
            },
        ],
        emailRateLimit: [
            null as HogFlowEmailSendingRateLimitApi | null,
            {
                setEmailRateLimit: (_, { emailRateLimit }) => emailRateLimit,
                hydrateFromBroadcast: (state, { broadcast }) => broadcast.email_sending_rate_limit ?? state,
                applyExternalEdit: (state, { broadcast, base }) =>
                    changedElsewhere(broadcast, base, (b) => b.email_sending_rate_limit)
                        ? (broadcast.email_sending_rate_limit ?? null)
                        : state,
            },
        ],
        emailSettings: [
            DEFAULT_BROADCAST_EMAIL_SETTINGS,
            {
                setEmailSettings: (state, { settings }) => ({ ...state, ...settings }),
                hydrateFromBroadcast: (state, { broadcast }) => readEmailSettings(broadcast) ?? state,
                applyExternalEdit: (state, { broadcast, base }) =>
                    changedElsewhere(broadcast, base, readEmailSettings)
                        ? (readEmailSettings(broadcast) ?? state)
                        : state,
            },
        ],
        email: [
            DEFAULT_BROADCAST_EMAIL,
            {
                setEmail: (_, { email }) => email,
                applyExternalEdit: (state, { broadcast }) => {
                    const value = findAction(broadcast, 'function_email')?.config?.inputs?.email?.value
                    return value ? { ...DEFAULT_BROADCAST_EMAIL, ...value } : state
                },
                hydrateFromBroadcast: (state, { broadcast }) => {
                    const emailAction = findAction(broadcast, 'function_email')
                    const value = emailAction?.config?.inputs?.email?.value
                    return value ? { ...DEFAULT_BROADCAST_EMAIL, ...value } : state
                },
            },
        ],
        scheduleMode: [
            'now' as BroadcastScheduleMode,
            {
                setScheduleMode: (_, { mode }) => mode,
                hydrateFromBroadcast: (state, { broadcast }) => {
                    const schedule = broadcast.schedules?.[0]
                    if (!schedule) {
                        return state
                    }
                    return isOneTimeSchedule(schedule.rrule) ? 'later' : 'recurring'
                },
            },
        ],
        sendAt: [
            null as string | null,
            {
                setSendAt: (_, { sendAt }) => sendAt,
                hydrateFromBroadcast: (state, { broadcast }) => {
                    const schedule = broadcast.schedules?.[0]
                    return schedule && isOneTimeSchedule(schedule.rrule) ? schedule.starts_at : state
                },
            },
        ],
        scheduleState: [
            DEFAULT_STATE,
            {
                setScheduleState: (_, { state }) => state,
                hydrateFromBroadcast: (state, { broadcast }) => {
                    const schedule = broadcast.schedules?.[0]
                    return schedule && !isOneTimeSchedule(schedule.rrule) ? parseRRuleToState(schedule.rrule) : state
                },
            },
        ],
        recurringStartsAt: [
            null as string | null,
            {
                setRecurringStartsAt: (_, { startsAt }) => startsAt,
                hydrateFromBroadcast: (state, { broadcast }) => {
                    const schedule = broadcast.schedules?.[0]
                    return schedule && !isOneTimeSchedule(schedule.rrule) ? schedule.starts_at : state
                },
            },
        ],
        recurringRepeating: [
            true,
            {
                setRecurringRepeating: (_, { repeating }) => repeating,
            },
        ],
        scheduleTimezone: [
            null as string | null,
            {
                setScheduleTimezone: (_, { timezone }) => timezone,
                hydrateFromBroadcast: (state, { broadcast }) => broadcast.schedules?.[0]?.timezone ?? state,
            },
        ],
        saving: [
            false,
            {
                continueStep: () => true,
                saveBroadcastFinished: () => false,
            },
        ],
        launching: [
            false,
            {
                launchBroadcast: () => true,
                launchBroadcastFinished: () => false,
            },
        ],
        hasLoadedBatchJobs: [
            false,
            {
                loadBatchJobs: () => false,
                loadBatchJobsSuccess: () => true,
            },
        ],
        movingToDraft: [
            false,
            {
                moveToDraft: () => true,
                moveToDraftFinished: () => false,
            },
        ],
        duplicating: [
            false,
            {
                duplicateBroadcast: () => true,
                duplicateBroadcastFinished: () => false,
            },
        ],
        // Set once the initial load of an existing draft has hydrated the reducers, so the wizard can
        // resume at the first incomplete step exactly once.
        hasHydrated: [
            props.id !== 'new' ? false : true,
            {
                hydrateFromBroadcast: () => true,
            },
        ],
    })),

    selectors({
        // The saved broadcast overlaid with the editor's unsaved state, in the shape the AI assistant reads.
        broadcastAsWorkflow: [
            (s) => [
                s.broadcast,
                s.name,
                s.audienceProperties,
                s.goalEnabled,
                s.conversion,
                s.email,
                s.emailRateLimit,
                s.emailSettings,
            ],
            (
                broadcast: HogFlowApi | null,
                name: string,
                audienceProperties: AnyPropertyFilter[],
                goalEnabled: boolean,
                conversion: HogFlowConversionApi,
                email: BroadcastEmailValue,
                emailRateLimit: HogFlowEmailSendingRateLimitApi | null,
                emailSettings: BroadcastEmailSettings
            ): HogFlowApi | null =>
                broadcast
                    ? ({
                          ...broadcast,
                          ...buildBroadcastPayload({
                              name,
                              audienceProperties,
                              goalEnabled,
                              conversion,
                              email,
                              emailRateLimit,
                              emailSettings,
                              // A workflow shaped like a broadcast keeps its own step ids in the agent's view.
                              broadcast,
                          }),
                          status: broadcast.status,
                      } as HogFlowApi)
                    : null,
        ],
        broadcastId: [
            (s, p) => [s.broadcast, p.id],
            (broadcast: HogFlowApi | null, id: string): string | null => broadcast?.id ?? (id !== 'new' ? id : null),
        ],
        // The latest run is what a sender opens a sent broadcast to read, so it starts expanded.
        expandedRunIds: [
            (s) => [s.expandedRunOverride, s.batchJobs],
            (override: string[] | null, batchJobs: HogFlowBatchJobApi[]): string[] =>
                override ?? (batchJobs[0]?.id ? [batchJobs[0].id] : []),
        ],
        canMoveToDraft: [
            (s) => [s.broadcast, s.batchJobs, s.hasLoadedBatchJobs],
            (broadcast: HogFlowApi | null, batchJobs: HogFlowBatchJobApi[], hasLoadedBatchJobs: boolean): boolean =>
                canMoveToDraft(broadcast as StoppableBroadcast | null, hasLoadedBatchJobs ? batchJobs : null),
        ],
        canEditContent: [
            (s) => [s.broadcast],
            (broadcast: HogFlowApi | null): boolean =>
                !!broadcast && canEditInWizard(broadcast.actions as any, broadcast.edges as any),
        ],
        summaryStatus: [
            (s) => [s.broadcast, s.batchJobs, s.hasLoadedBatchJobs],
            (
                broadcast: HogFlowApi | null,
                batchJobs: HogFlowBatchJobApi[],
                hasLoadedBatchJobs: boolean
            ): BroadcastStatus =>
                broadcast
                    ? getBroadcastStatus(
                          broadcast,
                          hasLoadedBatchJobs
                              ? {
                                    latestBatchJob: batchJobs[0] ?? null,
                                    totals: null,
                                    hasPendingSchedule: !!broadcast.schedules?.some(
                                        (schedule) => schedule.status === 'active'
                                    ),
                                }
                              : undefined
                      )
                    : 'unknown',
        ],
        isReadOnly: [
            (s) => [s.broadcast],
            (broadcast: HogFlowApi | null): boolean => !!broadcast && broadcast.status !== 'draft',
        ],
        effectiveTimezone: [
            (s) => [s.scheduleTimezone, s.currentTeam],
            (scheduleTimezone: string | null, currentTeam: TeamPublicType | TeamType | null): string =>
                scheduleTimezone ?? currentTeam?.timezone ?? dayjs.tz.guess(),
        ],
        selectedSender: [
            (s) => [s.email, s.integrations],
            (email: BroadcastEmailValue, integrations: IntegrationType[] | null): IntegrationType | null =>
                integrations?.find(
                    (integration) => integration.kind === 'email' && integration.id === email.from?.integrationId
                ) ?? null,
        ],
        stepValidationErrors: [
            (s) => [
                s.goalEnabled,
                s.conversion,
                s.email,
                s.scheduleMode,
                s.sendAt,
                s.recurringStartsAt,
                s.integrations,
                s.integrationsLoading,
            ],
            (
                goalEnabled: boolean,
                conversion: HogFlowConversionApi,
                email: BroadcastEmailValue,
                scheduleMode: BroadcastScheduleMode,
                sendAt: string | null,
                recurringStartsAt: string | null,
                integrations: IntegrationType[] | null,
                integrationsLoading: boolean
            ): Record<BroadcastWizardStep, string[]> => {
                const errors: Record<BroadcastWizardStep, string[]> = {
                    recipients: [],
                    goal: [],
                    content: [],
                    schedule: [],
                    review: [],
                }

                if (goalEnabled) {
                    const hasEventGoal = (conversion.events?.[0]?.filters?.events?.length ?? 0) > 0
                    const hasPropertyGoal = (conversion.filters?.length ?? 0) > 0
                    if (!hasEventGoal && !hasPropertyGoal) {
                        errors.goal.push('Add a conversion event or property, or choose no goal')
                    }
                }

                if (!email.from?.integrationId) {
                    errors.content.push('Choose an email sender')
                } else if (integrations && getMissingSenderIds(email.from, integrations).length > 0) {
                    // Shown on the content step, where the sender is picked, rather than first at launch.
                    errors.content.push(DELETED_SENDER_ERROR)
                }
                if (!email.subject) {
                    errors.content.push('Add a subject line')
                }
                if (!email.html && !email.text && !email.design) {
                    errors.content.push('Add email content')
                }

                if (scheduleMode === 'later') {
                    if (!sendAt) {
                        errors.schedule.push('Pick a send date and time')
                    } else if (dayjs(sendAt).isBefore(dayjs())) {
                        errors.schedule.push('The send time must be in the future')
                    }
                }
                if (scheduleMode === 'recurring' && !recurringStartsAt) {
                    errors.schedule.push('Pick a start date and time')
                }

                errors.review = [...errors.recipients, ...errors.goal, ...errors.content, ...errors.schedule]
                const senderError = getSenderLaunchError(email.from, integrations, integrationsLoading)
                if (senderError && !errors.review.includes(senderError)) {
                    errors.review.push(senderError)
                }

                return errors
            },
        ],
        currentStepHasErrors: [
            (s) => [s.stepValidationErrors, s.currentStep],
            (errors: Record<BroadcastWizardStep, string[]>, currentStep: BroadcastWizardStep): boolean =>
                errors[currentStep].length > 0,
        ],
        firstInvalidStep: [
            (s) => [s.stepValidationErrors],
            (errors: Record<BroadcastWizardStep, string[]>): BroadcastWizardStep | null =>
                BROADCAST_WIZARD_STEPS.find((step) => step !== 'review' && errors[step].length > 0) ?? null,
        ],
        scheduleSummary: [
            (s) => [
                s.scheduleMode,
                s.sendAt,
                s.scheduleState,
                s.recurringStartsAt,
                s.recurringRepeating,
                s.effectiveTimezone,
            ],
            (
                scheduleMode: BroadcastScheduleMode,
                sendAt: string | null,
                scheduleState: ScheduleState,
                recurringStartsAt: string | null,
                recurringRepeating: boolean,
                effectiveTimezone: string
            ): string => {
                if (scheduleMode === 'now') {
                    return 'Sends immediately'
                }
                if (scheduleMode === 'later') {
                    return sendAt
                        ? `Sends once on ${dayjs(sendAt).tz(effectiveTimezone).format('MMMM D, YYYY h:mm A')} (${effectiveTimezone})`
                        : 'No send time set'
                }
                if (!recurringStartsAt) {
                    return 'No start time set'
                }
                if (!recurringRepeating) {
                    return `Sends once on ${dayjs(recurringStartsAt).tz(effectiveTimezone).format('MMMM D, YYYY h:mm A')} (${effectiveTimezone})`
                }
                return buildSummary(scheduleState, recurringStartsAt, effectiveTimezone)
            },
        ],
        rateLimitedSendDuration: [
            (s) => [s.emailRateLimit, s.blastRadius],
            (emailRateLimit: HogFlowEmailSendingRateLimitApi | null, blastRadius: BlastRadiusApi | null): string => {
                const recipients = blastRadius?.affected
                if (!emailRateLimit || !recipients) {
                    return ''
                }
                // An estimate: the worker holds sends under the limit by rescheduling them, and it
                // retries on a jittered delay, so the real send runs a little longer than this.
                const perSecond = emailRateLimit.count / (emailRateLimit.period === 'hour' ? 3600 : 60)
                return humanFriendlyDuration(Math.ceil(recipients / perSecond), { maxUnits: 2 })
            },
        ],
        breadcrumbs: [
            (s) => [s.name],
            (name: string): Breadcrumb[] => [
                {
                    key: Scene.Broadcasts,
                    name: 'Broadcasts',
                    path: urls.broadcasts(),
                    iconType: 'broadcasts',
                },
                {
                    key: [Scene.Broadcast, name],
                    name,
                    iconType: 'broadcasts',
                },
            ],
        ],
    }),

    listeners(({ actions, values, props, cache }) => ({
        expandRun: ({ runId }) => {
            actions.setExpandedRunOverride([...values.expandedRunIds.filter((id) => id !== runId), runId])
        },
        collapseRun: ({ runId }) => {
            actions.setExpandedRunOverride(values.expandedRunIds.filter((id) => id !== runId))
        },
        setAudienceProperties: async (_, breakpoint) => {
            // Debounce so each filter keystroke doesn't fire a preview query.
            await breakpoint(500)
            actions.loadBlastRadius()
        },
        setStep: ({ step }) => {
            if (step === 'review') {
                // A fresh preview mints the confirm token launch needs and shows an up-to-date count.
                actions.loadBlastRadius()
            }
            if (step === 'content') {
                actions.ensureDraft()
            }
            actions.reportReviewVisit()
        },
        nextStep: () => {
            // Listeners run after reducers, so this sees the step just navigated to.
            if (values.currentStep === 'review') {
                actions.loadBlastRadius()
            }
            if (values.currentStep === 'content') {
                actions.ensureDraft()
            }
            actions.reportReviewVisit()
        },
        prevStep: () => {
            actions.reportReviewVisit()
        },
        reportReviewVisit: async (_, breakpoint) => {
            if (values.currentStep !== 'review') {
                cache.reviewBlockReported = false
                return
            }
            if (cache.reviewBlockReported) {
                return
            }
            // Senders load after the step renders, so let the blocking issues settle before reading them.
            await breakpoint(2000)
            const issues = values.stepValidationErrors.review
            if (values.currentStep !== 'review' || issues.length === 0 || values.integrationsLoading) {
                return
            }
            cache.reviewBlockReported = true
            // pinned: analytics event name
            posthog.capture('broadcast launch blocked', {
                broadcast_id: values.broadcastId,
                path: broadcastPath(values.broadcastId),
                blocking_issues: issues,
            })
        },
        applyExternalEdit: ({ broadcast, base }) => {
            // PostHog AI can change the recipients, so the audience size shown must follow.
            if (changedElsewhere(broadcast, base, readAudience)) {
                actions.loadBlastRadius()
            }
            const composerDraft = loadComposerDraft(broadcast.id)
            if (!composerDraft) {
                return
            }
            saveComposerDraft(broadcast.id, {
                agentDraft: advanceAgentDraft(
                    composerDraft.agentDraft,
                    snapshotBroadcast(broadcast),
                    base ? snapshotBroadcast(base) : null
                ),
                agentEdits: composerDraft.agentEdits + 1,
            })
        },
        ensureDraft: async () => {
            // The AI assistant edits the saved broadcast, so the content step needs one to exist even
            // when the stepper skipped past the Continue that would have created it. A Continue or launch
            // save still in flight creates the draft itself, so a create here would make a second one.
            const saves = getSaveQueue(cache, values)
            if (
                values.broadcastId ||
                saves.inFlight > 0 ||
                values.saving ||
                values.launching ||
                props.id !== 'new' ||
                !values.currentProjectId
            ) {
                return
            }
            const projectId = String(values.currentProjectId)
            try {
                await saves.run(async () => {
                    actions.draftAutosaved(await hogFlowsCreate(projectId, buildBroadcastPayload(values) as any))
                })
                actions.showSavedDraftUrl()
            } catch (error: any) {
                lemonToast.error(`Couldn't save the broadcast: ${error?.detail || error?.message || 'unknown error'}`)
            }
        },
        showSavedDraftUrl: () => {
            // On /broadcasts/new a reload starts over and orphans the saved draft. The new URL remounts the
            // wizard from the saved copy, so an unsaved email edit moves it only once its autosave lands.
            if (
                props.id === 'new' &&
                !cache.emailEditPending &&
                values.broadcastId &&
                values.broadcast?.status === 'draft'
            ) {
                router.actions.replace(urls.broadcast(values.broadcastId), { step: values.currentStep })
            }
        },
        setEmailSettings: () => {
            // Tracking and category live on the email step, so they share its autosave and pending flag.
            actions.setEmail(values.email)
        },
        setEmail: async (_, breakpoint) => {
            // Keeps the saved draft in step with the editor, so an AI edit starts from what the user
            // sees rather than from the last Continue.
            // The editor is live while the draft is still being created, so wait for it before the
            // draft check. Otherwise edits made during the create never reach the saved draft.
            // Overlapping autosaves share the pending flag, so only the latest edit may clear it. It is set
            // before the wait, so a draft created meanwhile does not leave /broadcasts/new without this edit.
            const generation = (cache.emailEditGeneration = (cache.emailEditGeneration ?? 0) + 1)
            const clearPending = (): void => {
                if (cache.emailEditGeneration === generation) {
                    cache.emailEditPending = false
                }
            }
            cache.emailEditPending = true
            // Read before the wait: a Continue in flight moves the step on, but its save may not carry this edit.
            const editedOnContent = values.currentStep === 'content'
            const saves = getSaveQueue(cache, values)
            await saves.whenIdle()
            if (!editedOnContent || values.broadcast?.status !== 'draft') {
                clearPending()
                return
            }
            await breakpoint(1000)
            if (!values.broadcastId || !values.currentProjectId || values.broadcast?.status !== 'draft') {
                // Launch saves this edit instead.
                clearPending()
                return
            }
            const projectId = String(values.currentProjectId)
            try {
                // Queued behind any save still in flight, and fenced on the copy that save wrote, so the
                // assistant's edit between two keystrokes comes back as a conflict instead of being lost.
                await saves.run(async () => {
                    actions.draftAutosaved(await saveWithoutClobbering(projectId, values.broadcastId!, values))
                    clearPending()
                })
                cache.emailAutosaveRetries = 0
                actions.showSavedDraftUrl()
            } catch (error: any) {
                if (error instanceof EditedElsewhereError) {
                    clearPending()
                    cache.autosaveConflict = true
                    actions.applyExternalEdit(error.latest, values.broadcast)
                    lemonToast.info(EDITED_ELSEWHERE_MESSAGE)
                } else if ((cache.emailAutosaveRetries ?? 0) < EMAIL_AUTOSAVE_RETRIES) {
                    // The edit stays pending, which keeps a new draft on /broadcasts/new until it saves, so retry
                    // a failed save rather than wait for Continue. Continue saves it and reports a lasting failure.
                    cache.emailAutosaveRetries = (cache.emailAutosaveRetries ?? 0) + 1
                    actions.replayDeferredEdit()
                    await breakpoint(EMAIL_AUTOSAVE_RETRY_MS)
                    actions.setEmail(values.email)
                    return
                }
            }
            actions.replayDeferredEdit()
        },
        saveName: async () => {
            // A new broadcast has no draft yet, and a live one is not renamed in place.
            if (
                !values.name.trim() ||
                !values.broadcastId ||
                !values.currentProjectId ||
                values.broadcast?.status !== 'draft' ||
                values.name === values.broadcast.name
            ) {
                return
            }
            const projectId = String(values.currentProjectId)
            try {
                await getSaveQueue(cache, values).run(async () => {
                    actions.draftAutosaved(
                        await patchWithoutClobbering(
                            projectId,
                            values.broadcastId!,
                            { name: values.name },
                            values.broadcast?.updated_at
                        )
                    )
                })
            } catch (error: any) {
                if (error instanceof EditedElsewhereError) {
                    // The rename stays local unless the other edit renamed it too, and the next save carries it.
                    const attempted = values.name
                    actions.applyExternalEdit(error.latest, values.broadcast)
                    if (values.name !== attempted) {
                        lemonToast.info("This broadcast was renamed somewhere else, so your new name wasn't saved.")
                    }
                } else {
                    lemonToast.error(`Couldn't save the name: ${error?.detail || error?.message || 'unknown error'}`)
                }
            }
            actions.replayDeferredEdit()
        },
        saveBroadcastFinished: () => {
            actions.replayDeferredEdit()
        },
        launchBroadcastFinished: () => {
            actions.replayDeferredEdit()
        },
        replayDeferredEdit: () => {
            const deferred = getSaveQueue(cache, values).takeDeferred()
            if (deferred) {
                actions.resourceEdited(deferred)
            }
        },
        resourceEdited: ({ event }) => {
            const broadcast = values.broadcast
            if (
                !broadcast ||
                broadcast.status !== 'draft' ||
                !values.currentProjectId ||
                getSaveQueue(cache, values).classify(event) !== 'external'
            ) {
                return
            }
            actions.loadExternalEdit()
        },
        loadExternalEdit: async (_, breakpoint) => {
            const broadcast = values.broadcast
            if (!broadcast || broadcast.status !== 'draft' || !values.currentProjectId) {
                return
            }
            await getSaveQueue(cache, values).whenIdle()
            await breakpoint(200)
            const fresh = await hogFlowsRetrieve(String(values.currentProjectId), broadcast.id).catch(() => null)
            breakpoint()
            if (!fresh) {
                lemonToast.error("Couldn't load the latest version of the broadcast. Reload the page to see it.")
                return
            }
            // A save can land while the fetch runs. Do not replace that newer state with an older copy.
            if (values.broadcast && !dayjs(fresh.updated_at).isAfter(dayjs(values.broadcast.updated_at))) {
                return
            }
            if (cache.emailEditPending) {
                // The saved version wins, as in the workflow editor, but not without saying so.
                cache.emailEditPending = false
                lemonToast.info(EDITED_ELSEWHERE_MESSAGE)
            }
            actions.applyExternalEdit(fresh, values.broadcast)
        },
        setSendAtFromPicker: ({ pickerDate }) => {
            if (!pickerDate) {
                actions.setSendAt(null)
                return
            }
            // The picker returns browser-local time; reinterpret it in the schedule timezone.
            const wallClock = dayjs(pickerDate).startOf('minute').format('YYYY-MM-DDTHH:mm:ss')
            actions.setSendAt(dayjs.tz(wallClock, values.effectiveTimezone).toISOString())
        },
        setRecurringStartsAtFromPicker: ({ pickerDate }) => {
            if (!pickerDate) {
                actions.setRecurringStartsAt(null)
                return
            }
            const wallClock = dayjs(pickerDate).startOf('minute').format('YYYY-MM-DDTHH:mm:ss')
            actions.setRecurringStartsAt(dayjs.tz(wallClock, values.effectiveTimezone).toISOString())
        },
        setScheduleTimezone: ({ timezone, previousTimezone }) => {
            // Keep the wall-clock time when the timezone changes, matching the workflow editor.
            const oldTz = previousTimezone ?? dayjs.tz.guess()
            if (values.sendAt) {
                const wallClock = dayjs(values.sendAt).tz(oldTz).format('YYYY-MM-DDTHH:mm:ss')
                actions.setSendAt(dayjs.tz(wallClock, timezone).toISOString())
            }
            if (values.recurringStartsAt) {
                const wallClock = dayjs(values.recurringStartsAt).tz(oldTz).format('YYYY-MM-DDTHH:mm:ss')
                actions.setRecurringStartsAt(dayjs.tz(wallClock, timezone).toISOString())
            }
        },
        continueStep: async (_, breakpoint) => {
            if (values.currentStepHasErrors || !values.currentProjectId) {
                actions.saveBroadcastFinished(null)
                return
            }
            // A draft create or autosave still in flight must land first: the create so this doesn't make
            // a second draft, the autosave so a conflict it found stops this save.
            cache.autosaveConflict = false
            const saves = getSaveQueue(cache, values)
            await saves.whenIdle()
            breakpoint()
            if (cache.autosaveConflict) {
                // That autosave loaded an edit made elsewhere and said so. Let the user review it first.
                actions.saveBroadcastFinished(null)
                return
            }
            const projectId = String(values.currentProjectId)
            let savedEditGeneration: number | undefined
            try {
                const saved = await saves.run(() => {
                    savedEditGeneration = cache.emailEditGeneration
                    return values.broadcastId
                        ? saveWithoutClobbering(projectId, values.broadcastId, values)
                        : hogFlowsCreate(projectId, buildBroadcastPayload(values) as any)
                })
                actions.saveBroadcastFinished(saved)
                // This save carried the email edits made before it started. A later one keeps its own autosave.
                if (cache.emailEditGeneration === savedEditGeneration) {
                    cache.emailEditPending = false
                }
                actions.nextStep()
                actions.showSavedDraftUrl()
            } catch (error: any) {
                actions.saveBroadcastFinished(null)
                if (error instanceof EditedElsewhereError) {
                    actions.applyExternalEdit(error.latest, values.broadcast)
                    lemonToast.info(
                        'This email changed while you were editing it. Review the latest version, then continue.'
                    )
                    return
                }
                lemonToast.error(`Couldn't save the broadcast: ${error?.detail || error?.message || 'unknown error'}`)
            }
        },
        launchBroadcast: async (_, breakpoint) => {
            if (!values.currentProjectId) {
                actions.launchBroadcastFinished()
                return
            }
            if (values.firstInvalidStep) {
                actions.launchBroadcastFinished()
                actions.setStep(values.firstInvalidStep)
                return
            }
            const projectId = String(values.currentProjectId)
            // Same ordering as Continue: a save that trails the content step must land first.
            cache.autosaveConflict = false
            const saves = getSaveQueue(cache, values)
            await saves.whenIdle()
            breakpoint()
            if (cache.autosaveConflict) {
                captureLaunchFailed(values.broadcastId, 'edited_elsewhere')
                actions.launchBroadcastFinished()
                return
            }
            let broadcastId = values.broadcastId
            let activated: HogFlowApi | null = null
            try {
                // Save the latest edits (creating the draft if the user skipped ahead).
                const saved = await saves.run(() =>
                    broadcastId
                        ? saveWithoutClobbering(projectId, broadcastId, values)
                        : hogFlowsCreate(projectId, buildBroadcastPayload(values) as any)
                )
                broadcastId = saved.id
                actions.saveBroadcastFinished(saved)

                // A fresh audience preview mints the confirm token the batch dispatch expects.
                const blastRadius = await hogFlowsUserBlastRadiusCreate(projectId, {
                    filters: { properties: values.audienceProperties },
                    dedupe_key: 'email',
                })

                // The resolver silently caps the batch at this limit, so dispatching an audience over
                // it would confirm N recipients and deliver to the first slice. Stop at the step that
                // can fix it. Mirrors the guard on the workflow editor's manual trigger.
                if (blastRadius.limit != null && blastRadius.affected > blastRadius.limit) {
                    captureLaunchFailed(broadcastId, 'audience_over_limit')
                    actions.launchBroadcastFinished()
                    actions.setStep('recipients')
                    actions.showSavedDraftUrl()
                    lemonToast.error(
                        `This project can send a broadcast to up to ${humanFriendlyNumber(
                            blastRadius.limit
                        )} people right now. Add filters to narrow the audience, then launch again.`,
                        {
                            button: {
                                label: 'See sending limits',
                                action: () => router.actions.push(urls.workflows('reputation')),
                                dataAttr: 'broadcast-launch-limit-see-sending-limits',
                            },
                        }
                    )
                    return
                }

                // The assistant can edit the draft during the audience request. Activate only the saved
                // version, so the send never goes out with an email the user did not see. Schedule
                // changes don't bump the flow's updated_at, so the base stays valid across the swap.
                const toActivate = broadcastId
                const activate = (): Promise<HogFlowApi> =>
                    saves.run(() =>
                        patchWithoutClobbering(projectId, toActivate, { status: 'active' }, saved.updated_at)
                    )
                // An old schedule would fire alongside the new one, and a paused one can't be resumed, so
                // launch replaces them. The flow stays a draft until the swap is done, and the scheduler
                // skips drafts, so a failure part way never leaves two live schedules or none.
                const oldScheduleIds = (values.broadcast?.schedules ?? []).map((existing) => existing.id)
                // Stop before touching schedules if the assistant saved meanwhile. Otherwise the guarded
                // activation below would 409 after the old schedule is already gone.
                const current = await hogFlowsRetrieve(projectId, toActivate)
                if (current.updated_at !== saved.updated_at) {
                    throw new EditedElsewhereError(current)
                }
                if (values.scheduleMode === 'now') {
                    for (const id of oldScheduleIds) {
                        await hogFlowsSchedulesDestroy(projectId, broadcastId, id)
                    }
                    activated = await activate()
                    await hogFlowsBatchJobsCreate(projectId, broadcastId, {
                        hog_flow: broadcastId,
                        variables: {},
                        confirm_token: blastRadius.confirm_token,
                    } as any)
                    lemonToast.success('Broadcast is sending')
                } else {
                    const schedule: Partial<HogFlowScheduleApi> = {
                        rrule:
                            values.scheduleMode === 'recurring' && values.recurringRepeating
                                ? stateToRRule(values.scheduleState, values.recurringStartsAt)
                                : ONE_TIME_RRULE,
                        starts_at: (values.scheduleMode === 'recurring' ? values.recurringStartsAt : values.sendAt)!,
                        timezone: values.effectiveTimezone,
                        // The wizard has no variables step, so keep any overrides the old schedule carried.
                        ...(values.broadcast?.schedules?.[0]?.variables
                            ? { variables: values.broadcast.schedules[0].variables }
                            : {}),
                    }
                    await hogFlowsSchedulesCreate(projectId, broadcastId, schedule as any)
                    for (const id of oldScheduleIds) {
                        await hogFlowsSchedulesDestroy(projectId, broadcastId, id)
                    }
                    activated = await activate()
                    lemonToast.success('Broadcast scheduled')
                }
                // Resuming a draft launches from the broadcast's own URL, so the router push below is a
                // no-op there. Store the activated broadcast so the scene swaps to the read-only summary
                // instead of leaving a live send button on a broadcast that already went out.
                actions.saveBroadcastFinished(activated)
                const composerDraft = loadComposerDraft(broadcastId)
                // pinned: analytics event name
                posthog.capture('broadcast launched', {
                    broadcast_id: broadcastId,
                    path: broadcastPath(broadcastId),
                    schedule_mode: values.scheduleMode,
                    audience_filter_count: values.audienceProperties.length,
                    has_goal: values.goalEnabled,
                    entry_source: values.entrySource,
                    seconds_since_created: activated
                        ? Math.round((Date.now() - new Date(activated.created_at).getTime()) / 1000)
                        : null,
                    ...(composerDraft
                        ? {
                              edited_fields: editedFields(
                                  composerDraft.agentDraft,
                                  snapshotBroadcast(buildBroadcastPayload(values))
                              ),
                              agent_edits_after_draft: composerDraft.agentEdits,
                          }
                        : {}),
                })
                actions.loadBatchJobs()
                actions.launchBroadcastFinished()
                router.actions.push(urls.broadcast(broadcastId))
            } catch (error: any) {
                if (error instanceof EditedElsewhereError) {
                    captureLaunchFailed(broadcastId, 'edited_elsewhere')
                    actions.applyExternalEdit(error.latest, values.broadcast)
                    actions.launchBroadcastFinished()
                    lemonToast.info(
                        'This email changed while you were editing it. Review the latest version, then launch.'
                    )
                    actions.showSavedDraftUrl()
                    return
                }
                if (activated && broadcastId) {
                    // Activation landed but the send did not. An active broadcast with no job and no
                    // schedule is read-only, so leaving it there would strand it with no way to retry.
                    try {
                        await hogFlowsPartialUpdate(projectId, broadcastId, { status: 'draft' })
                    } catch {
                        lemonToast.error('The broadcast is still active but has nothing scheduled. Reload the page.')
                    }
                }
                captureLaunchFailed(broadcastId, 'error')
                actions.launchBroadcastFinished()
                lemonToast.error(`Couldn't launch the broadcast: ${error?.detail || error?.message || 'unknown error'}`)
                // The launch saved the draft first, so a reload of /broadcasts/new would orphan it.
                actions.showSavedDraftUrl()
            }
        },
        moveToDraft: async () => {
            if (!values.currentProjectId || !values.broadcastId) {
                actions.moveToDraftFinished()
                return
            }
            const projectId = String(values.currentProjectId)
            const broadcastId = values.broadcastId
            try {
                // The scheduler skips a draft flow; the schedule stays so the wizard shows its timing.
                const draft = await hogFlowsPartialUpdate(projectId, broadcastId, { status: 'draft' })
                actions.setStep('review')
                actions.saveBroadcastFinished(draft)
            } catch (error: any) {
                lemonToast.error(
                    `Couldn't move the broadcast to draft: ${error?.detail || error?.message || 'unknown error'}`
                )
                actions.moveToDraftFinished()
                return
            }
            try {
                // A run the scheduler started before the stop landed is still live, so stop it too.
                const jobs = await hogFlowsBatchJobsList(projectId, broadcastId)
                const started = jobs.filter((job) => ['waiting', 'queued', 'active'].includes(job.status ?? ''))
                for (const job of started) {
                    await hogFlowsBatchJobsCancelCreate(projectId, broadcastId, job.id)
                }
                if (started.length) {
                    lemonToast.warning(
                        'A send had just started, so it was cancelled. Any emails it already sent are not recalled.'
                    )
                } else {
                    lemonToast.success('Broadcast moved to draft')
                }
            } catch (error: any) {
                lemonToast.error(
                    `The broadcast is a draft, but a send that had just started couldn't be cancelled: ${
                        error?.detail || error?.message || 'unknown error'
                    }`
                )
            }
            actions.moveToDraftFinished()
        },
        archiveBroadcast: () => {
            if (values.currentProjectId && values.broadcast) {
                confirmArchiveBroadcast(String(values.currentProjectId), values.broadcast, actions.loadBroadcast)
            }
        },
        restoreBroadcast: async () => {
            if (values.currentProjectId && values.broadcast) {
                await restoreBroadcast(String(values.currentProjectId), values.broadcast, actions.loadBroadcast)
            }
        },
        deleteBroadcast: () => {
            if (values.currentProjectId && values.broadcast) {
                confirmDeleteBroadcast(String(values.currentProjectId), values.broadcast, () =>
                    router.actions.push(urls.broadcasts())
                )
            }
        },
        duplicateBroadcast: async () => {
            if (!values.currentProjectId) {
                actions.duplicateBroadcastFinished()
                return
            }
            try {
                // A fresh broadcast with this one's audience and email, so sending again goes through
                // the wizard's review and launch like any other send.
                const copy = await hogFlowsCreate(
                    String(values.currentProjectId),
                    buildBroadcastPayload({ ...values, name: `${values.name} (copy)`, broadcast: null }) as any
                )
                actions.duplicateBroadcastFinished()
                router.actions.push(urls.broadcast(copy.id))
            } catch (error: any) {
                actions.duplicateBroadcastFinished()
                lemonToast.error(`Couldn't copy the broadcast: ${error?.detail || error?.message || 'unknown error'}`)
            }
        },
        loadBroadcastSuccess: ({ broadcast }) => {
            if (!broadcast || values.hasHydrated) {
                return
            }
            actions.hydrateFromBroadcast(broadcast)
            if (broadcast.status !== 'draft') {
                actions.loadBatchJobs()
            }
        },
        hydrateFromBroadcast: ({ broadcast }) => {
            if (values.broadcast?.status !== 'draft') {
                return
            }
            // A draft just saved from /broadcasts/new carries the step it was on, and a composer draft says so.
            // Otherwise resume at the first incomplete step; complete drafts land on review.
            const { step, [COMPOSER_DRAFT_PARAM]: from, ...searchParams } = router.values.searchParams
            if (from === COMPOSER_DRAFT_VALUE && !loadComposerDraft(broadcast.id)) {
                // What the agent drafted, so the launch can report which fields the person changed.
                saveComposerDraft(broadcast.id, { agentDraft: snapshotBroadcast(broadcast), agentEdits: 0 })
            }
            if (BROADCAST_WIZARD_STEPS.includes(step)) {
                actions.setStep(step)
            } else {
                actions.setStep(values.firstInvalidStep ?? 'review')
            }
            if (step !== undefined || from !== undefined) {
                router.actions.replace(router.values.location.pathname, searchParams, router.values.hashParams)
            }
        },
        loadBroadcastFailure: () => {
            lemonToast.error("Couldn't load the broadcast. Refresh the page to try again.")
        },
    })),

    afterMount(({ actions, props }) => {
        if (props.id !== 'new') {
            actions.loadBroadcast()
            return
        }
        const {
            [AUDIENCE_PREFILL_PARAM]: audience,
            [NAME_PREFILL_PARAM]: name,
            [SOURCE_PREFILL_PARAM]: source,
            ...searchParams
        } = router.values.searchParams
        const properties = parseBroadcastAudiencePrefill(audience)
        if (properties) {
            const prefill: BroadcastPrefill = {
                properties,
                name: typeof name === 'string' ? name : undefined,
                source: typeof source === 'string' ? source : undefined,
            }
            // Not setAudienceProperties: opening /broadcasts/new must not create a draft.
            actions.prefillFromLink(prefill)
            // pinned: analytics event name
            posthog.capture('broadcast prefilled from link', {
                entry_source: prefill.source ?? null,
                audience_filter_count: properties.length,
            })
        }
        if (audience !== undefined && !properties) {
            // Opening with no recipients would mean everyone, so say the link's audience was not used.
            lemonToast.error("This link's recipients couldn't be read, so none were added. Choose who gets the email.")
        }
        if (audience !== undefined || name !== undefined || source !== undefined) {
            router.actions.replace(router.values.location.pathname, searchParams, router.values.hashParams)
        }
        actions.loadBlastRadius()
    }),
])

function captureLaunchFailed(
    broadcastId: string | null | undefined,
    reason: 'audience_over_limit' | 'edited_elsewhere' | 'error'
): void {
    // pinned: analytics event name
    posthog.capture('broadcast launch failed', { broadcast_id: broadcastId, path: broadcastPath(broadcastId), reason })
}

function getSaveQueue(cache: Record<string, any>, values: broadcastWizardLogicType['values']): ResourceSaveQueue {
    return (cache.saveQueue ??= new ResourceSaveQueue({
        resourceType: 'HogFlow',
        getResourceId: () => values.broadcast?.id,
        getLoadedStamp: () => values.broadcast?.updated_at,
        // Continue and launch save outside an autosave, and their echo can arrive before they finish.
        isBusy: () => values.saving || values.launching,
    }))
}

const EDITED_ELSEWHERE_MESSAGE = 'This email changed elsewhere, so your last few seconds of edits were replaced.'

class EditedElsewhereError extends Error {
    constructor(public latest: HogFlowApi) {
        super('The broadcast was edited elsewhere')
    }
}

// Saves with the updated_at last loaded, so an edit saved elsewhere since (e.g. by PostHog AI) comes
// back as a conflict instead of being overwritten by an editor that has not shown it yet.
async function saveWithoutClobbering(
    projectId: string,
    broadcastId: string,
    values: Parameters<typeof buildBroadcastPayload>[0] & { broadcast: HogFlowApi | null }
): Promise<HogFlowApi> {
    return await patchWithoutClobbering(
        projectId,
        broadcastId,
        buildBroadcastPayload(values),
        values.broadcast?.updated_at
    )
}

async function patchWithoutClobbering(
    projectId: string,
    broadcastId: string,
    payload: Record<string, any>,
    baseUpdatedAt: string | undefined
): Promise<HogFlowApi> {
    try {
        return await hogFlowsPartialUpdate(projectId, broadcastId, {
            ...payload,
            base_updated_at: baseUpdatedAt,
        } as any)
    } catch (error: any) {
        if (error?.status === 409) {
            throw new EditedElsewhereError(await hogFlowsRetrieve(projectId, broadcastId))
        }
        throw error
    }
}

export const SENDERS_LOAD_FAILED_ERROR = "Couldn't load your email senders. Reload them to launch."
export const DELETED_SENDER_ERROR = 'The chosen sender was deleted. Choose another sender.'

/**
 * Why the chosen sender can't send yet, if it can't. A draft can be written with any sender, but a
 * launch whose sender is unverified, deleted, or not yet known would fail every email it sends.
 */
export function getSenderLaunchError(
    from: BroadcastEmailValue['from'] | undefined,
    integrations: IntegrationType[] | null,
    integrationsLoading: boolean
): string | null {
    const senderIds = getSenderIds(from)
    if (senderIds.length === 0) {
        return null
    }
    if (!integrations) {
        return integrationsLoading ? 'Checking the email sender. Try again in a moment.' : SENDERS_LOAD_FAILED_ERROR
    }
    if (getMissingSenderIds(from, integrations).length > 0) {
        return DELETED_SENDER_ERROR
    }
    const allVerified = senderIds.every(
        (id) =>
            integrations.find((integration) => integration.kind === 'email' && integration.id === id)?.config
                ?.verified === true
    )
    return allVerified ? null : "Verify the sender's domain before sending"
}

export function getSenderIds(from: BroadcastEmailValue['from'] | undefined): number[] {
    if (from?.integrationIds?.length) {
        return from.integrationIds
    }
    return from?.integrationId ? [from.integrationId] : []
}

export function getMissingSenderIds(
    from: BroadcastEmailValue['from'] | undefined,
    integrations: IntegrationType[]
): number[] {
    return getSenderIds(from).filter(
        (id) => !integrations.some((integration) => integration.kind === 'email' && integration.id === id)
    )
}

// Serializes the wizard state into the HogFlow the broadcast is stored as: a batch trigger
// (the audience), one email action, and an exit node.
export function buildBroadcastPayload(values: {
    name: string
    audienceProperties: AnyPropertyFilter[]
    goalEnabled: boolean
    conversion: HogFlowConversionApi
    email: BroadcastEmailValue
    emailRateLimit: HogFlowEmailSendingRateLimitApi | null
    emailSettings?: BroadcastEmailSettings
    broadcast?: HogFlowApi | null
}): Record<string, any> {
    const existing = values.broadcast
    if (existing && existing.origin_product !== 'broadcasts') {
        // A workflow shaped like a broadcast keeps its own steps: its ids, names and any setting the
        // wizard does not manage survive, and origin_product stays as it was created.
        return {
            name: values.name,
            conversion: values.goalEnabled ? values.conversion : null,
            email_sending_rate_limit: values.emailRateLimit,
            actions: (existing.actions as Record<string, any>[]).map((action) =>
                action.type === 'trigger'
                    ? {
                          ...action,
                          config: {
                              ...action.config,
                              filters: { ...action.config?.filters, properties: values.audienceProperties },
                          },
                      }
                    : action.type === 'function_email'
                      ? {
                            ...action,
                            config: {
                                ...action.config,
                                ...emailSettingsConfig(values.emailSettings),
                                inputs: {
                                    ...action.config?.inputs,
                                    email: { ...action.config?.inputs?.email, value: values.email },
                                },
                            },
                        }
                      : action
            ),
            edges: existing.edges,
        }
    }
    return {
        origin_product: 'broadcasts',
        status: 'draft',
        name: values.name,
        exit_condition: 'exit_only_at_end',
        conversion: values.goalEnabled ? values.conversion : null,
        email_sending_rate_limit: values.emailRateLimit,
        actions: [
            {
                id: TRIGGER_ACTION_ID,
                type: 'trigger',
                name: 'Audience',
                description: 'People this broadcast is sent to.',
                created_at: 0,
                updated_at: 0,
                config: {
                    type: 'batch',
                    filters: { properties: values.audienceProperties },
                },
            },
            {
                id: EMAIL_ACTION_ID,
                type: 'function_email',
                name: 'Send email',
                description: 'The broadcast email.',
                created_at: 0,
                updated_at: 0,
                config: {
                    template_id: 'template-email',
                    ...emailSettingsConfig(values.emailSettings),
                    inputs: {
                        email: { value: values.email },
                    },
                },
            },
            {
                id: EXIT_ACTION_ID,
                type: 'exit',
                name: 'Exit',
                description: 'Broadcast sent.',
                created_at: 0,
                updated_at: 0,
                config: { reason: 'Broadcast sent' },
            },
        ],
        edges: [
            { from: TRIGGER_ACTION_ID, to: EMAIL_ACTION_ID, type: 'continue' },
            { from: EMAIL_ACTION_ID, to: EXIT_ACTION_ID, type: 'continue' },
        ],
    }
}

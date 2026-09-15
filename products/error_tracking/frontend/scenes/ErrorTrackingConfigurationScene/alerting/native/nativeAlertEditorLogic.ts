import { MakeLogicType, actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { AnyPropertyFilter } from '~/types'

import {
    errorTrackingAlertsCreate,
    errorTrackingAlertsDestroy,
    errorTrackingAlertsPreviewRetrieve,
    errorTrackingAlertsUpdate,
} from '../../../../generated/api'
import {
    ErrorTrackingAlertApi,
    ErrorTrackingAlertDestinationRequestApi,
    ErrorTrackingAlertFiltersApi,
    ErrorTrackingAlertPreviewApi,
    ErrorTrackingAlertPutRequestApi,
    TriggersEnumApi,
} from '../../../../generated/api.schemas'
import { nativeAlertsLogic } from './nativeAlertsLogic'

export type DraftDestination = {
    integrationId: number | null
    /** The SlackChannelPicker's composite `CHANNEL_ID|#name` value. */
    channel: string | null
    /** Also post each thread reply to the channel. */
    replyBroadcast: boolean
}

const EMPTY_DESTINATION: DraftDestination = { integrationId: null, channel: null, replyBroadcast: true }

export type AlertDraft = {
    id: string | null
    name: string
    enabled: boolean
    triggers: TriggersEnumApi[]
    /** The stored filter shape minus `properties`, kept so fields the editor does not show survive a save. */
    otherFilters: Omit<ErrorTrackingAlertFiltersApi, 'properties' | 'bytecode'>
    properties: AnyPropertyFilter[]
    throttleSeconds: number
    destinations: DraftDestination[]
}

export const TRIGGER_OPTIONS: { value: TriggersEnumApi; label: string; short: string; description: string }[] = [
    { value: 'issue_created', label: 'Created', short: 'created', description: 'The first exception of a new issue' },
    {
        value: 'issue_reopened',
        label: 'Reopened',
        short: 'reopened',
        description: 'A new exception on a resolved issue',
    },
    {
        value: 'issue_spiking',
        label: 'Spiking',
        short: 'spiking',
        description: 'The issue is occurring far above its baseline',
    },
    { value: 'issue_assigned', label: 'Assigned', short: 'assigned', description: 'Someone is assigned to the issue' },
]
export const ALL_TRIGGERS: TriggersEnumApi[] = TRIGGER_OPTIONS.map((option) => option.value)

export function hasEveryTrigger(triggers: TriggersEnumApi[]): boolean {
    return ALL_TRIGGERS.every((trigger) => triggers.includes(trigger))
}

/** One sentence for what starts a thread; the card and the editor say the same thing. */
export function triggerSentence(triggers: TriggersEnumApi[]): string {
    if (hasEveryTrigger(triggers)) {
        return 'Starts a thread when anything happens to a matching issue.'
    }
    const names = TRIGGER_OPTIONS.filter((option) => triggers.includes(option.value)).map((option) => option.short)
    if (names.length === 0) {
        return 'Pick at least one event that starts a thread.'
    }
    const list = names.length === 1 ? names[0] : `${names.slice(0, -1).join(', ')} or ${names[names.length - 1]}`
    return `Starts a thread only when a matching issue is ${list}.`
}

export const THROTTLE_OPTIONS: { value: number; label: string }[] = [
    { value: 0, label: 'Every time' },
    { value: 5 * 60, label: 'Once every 5 minutes' },
    { value: 60 * 60, label: 'Once an hour' },
    { value: 6 * 60 * 60, label: 'Once every 6 hours' },
    { value: 24 * 60 * 60, label: 'Once a day' },
]

const projectId = (): string => String(teamLogic.values.currentProjectId)

function emptyDraft(): AlertDraft {
    return {
        id: null,
        name: '',
        enabled: true,
        triggers: [...ALL_TRIGGERS],
        otherFilters: {},
        properties: [],
        throttleSeconds: 0,
        destinations: [EMPTY_DESTINATION],
    }
}

/** Slack pickers hand back `CHANNEL_ID|#name`; the API stores the two halves separately. */
export function splitChannel(value: string | null): { channel: string; channelName: string } | null {
    if (!value) {
        return null
    }
    const [channel, channelName = ''] = value.split('|')
    return channel ? { channel, channelName } : null
}

export function joinChannel(channel: string, channelName: string | undefined): string {
    return channelName ? `${channel}|${channelName}` : channel
}

export function draftFromAlert(alert: ErrorTrackingAlertApi): AlertDraft {
    return {
        id: alert.id,
        name: alert.name,
        enabled: alert.enabled,
        triggers: [...alert.triggers],
        otherFilters: (({ properties: _properties, bytecode: _bytecode, ...rest }) => rest)(alert.filters),
        properties: ((alert.filters.properties ?? []) as AnyPropertyFilter[]).map((property) => ({ ...property })),
        throttleSeconds: alert.throttle_seconds,
        destinations: alert.destinations.map((destination) => ({
            integrationId: destination.integration_id ?? null,
            channel: destination.config.channel
                ? joinChannel(destination.config.channel, destination.config.channel_name)
                : null,
            replyBroadcast: destination.config.reply_broadcast ?? true,
        })),
    }
}

export function payloadFromDraft(draft: AlertDraft): ErrorTrackingAlertPutRequestApi {
    const destinations: ErrorTrackingAlertDestinationRequestApi[] = []
    for (const destination of draft.destinations) {
        const parsed = splitChannel(destination.channel)
        if (destination.integrationId !== null && parsed) {
            destinations.push({
                channel_type: 'slack',
                integration_id: destination.integrationId,
                config: {
                    channel: parsed.channel,
                    channel_name: parsed.channelName,
                    reply_broadcast: destination.replyBroadcast,
                },
            })
        }
    }
    return {
        name: draft.name.trim(),
        enabled: draft.enabled,
        triggers: draft.triggers,
        // The generated type carries the read-only `bytecode`; the server compiles it on save.
        filters: { ...draft.otherFilters, properties: draft.properties } as unknown as ErrorTrackingAlertFiltersApi,
        throttle_seconds: draft.throttleSeconds,
        destinations,
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface nativeAlertEditorLogicValues {
    customizingTriggers: boolean
    deleting: boolean
    deletingLoading: boolean
    draft: AlertDraft
    isOpen: boolean
    preview: ErrorTrackingAlertPreviewApi | null
    previewError: string | null
    previewLoading: boolean
    primaryTrigger: TriggersEnumApi
    saveDisabledReason: string | null
    saving: boolean
    savingLoading: boolean
    triggersCustomized: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface nativeAlertEditorLogicActions {
    loadAlerts: () => any // nativeAlertsLogic
    addDestination: () => {
        value: true
    }
    closeEditor: () => {
        value: true
    }
    customizeTriggers: () => {
        value: true
    }
    deleteAlert: () => any
    deleteAlertFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    deleteAlertSuccess: (
        deleting: boolean,
        payload?: any
    ) => {
        deleting: boolean
        payload?: any
    }
    loadPreview: ({ trigger }: { trigger: TriggersEnumApi }) => {
        trigger: TriggersEnumApi
    }
    loadPreviewFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadPreviewSuccess: (
        preview: ErrorTrackingAlertPreviewApi,
        payload?: {
            trigger: TriggersEnumApi
        }
    ) => {
        preview: ErrorTrackingAlertPreviewApi
        payload?: {
            trigger: TriggersEnumApi
        }
    }
    openEditor: (alert?: ErrorTrackingAlertApi) => {
        alert: ErrorTrackingAlertApi | null
    }
    removeDestination: (index: number) => {
        index: number
    }
    resetTriggers: () => {
        value: true
    }
    saveAlert: () => any
    saveAlertFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    saveAlertSuccess: (
        saving: boolean,
        payload?: any
    ) => {
        saving: boolean
        payload?: any
    }
    setDraft: (patch: Partial<AlertDraft>) => {
        patch: Partial<AlertDraft>
    }
    setTriggerEnabled: (
        trigger: TriggersEnumApi,
        enabled: boolean
    ) => {
        enabled: boolean
        trigger: TriggersEnumApi
    }
    updateDestination: (
        index: number,
        patch: Partial<DraftDestination>
    ) => {
        index: number
        patch: Partial<DraftDestination>
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface nativeAlertEditorLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        triggersCustomized: (draft: AlertDraft, customizingTriggers: any) => boolean
        primaryTrigger: (draft: AlertDraft) => TriggersEnumApi
        saveDisabledReason: (draft: AlertDraft) => string | null
    }
}

export type nativeAlertEditorLogicType = MakeLogicType<
    nativeAlertEditorLogicValues,
    nativeAlertEditorLogicActions,
    Record<string, any>,
    nativeAlertEditorLogicMeta
>

export const nativeAlertEditorLogic = kea<nativeAlertEditorLogicType>([
    path([
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingConfigurationScene',
        'alerting',
        'native',
        'nativeAlertEditorLogic',
    ]),

    connect(() => ({ actions: [nativeAlertsLogic, ['loadAlerts']] })),

    actions({
        openEditor: (alert?: ErrorTrackingAlertApi) => ({ alert: alert ?? null }),
        closeEditor: true,
        setDraft: (patch: Partial<AlertDraft>) => ({ patch }),
        setTriggerEnabled: (trigger: TriggersEnumApi, enabled: boolean) => ({ trigger, enabled }),
        customizeTriggers: true,
        resetTriggers: true,
        addDestination: true,
        updateDestination: (index: number, patch: Partial<DraftDestination>) => ({ index, patch }),
        removeDestination: (index: number) => ({ index }),
    }),

    reducers({
        isOpen: [false, { openEditor: () => true, closeEditor: () => false }],
        // The checkboxes stay hidden until someone asks for them or the saved alert needs them.
        customizingTriggers: [
            false,
            {
                openEditor: () => false,
                customizeTriggers: () => true,
                setTriggerEnabled: () => true,
                resetTriggers: () => false,
            },
        ],
        // A stale preview must not pose as the new trigger's thread while it loads or after it fails.
        preview: { loadPreview: () => null },
        previewError: [
            null as string | null,
            { loadPreview: () => null, loadPreviewSuccess: () => null, loadPreviewFailure: (_, { error }) => error },
        ],
        draft: [
            emptyDraft(),
            {
                openEditor: (_, { alert }) => (alert ? draftFromAlert(alert) : emptyDraft()),
                setDraft: (draft, { patch }) => ({ ...draft, ...patch }),
                setTriggerEnabled: (draft, { trigger, enabled }) => ({
                    ...draft,
                    triggers: enabled
                        ? [...new Set([...draft.triggers, trigger])]
                        : draft.triggers.filter((existing) => existing !== trigger),
                }),
                resetTriggers: (draft) => ({ ...draft, triggers: [...ALL_TRIGGERS] }),
                addDestination: (draft) => ({
                    ...draft,
                    destinations: [...draft.destinations, EMPTY_DESTINATION],
                }),
                updateDestination: (draft, { index, patch }) => ({
                    ...draft,
                    destinations: draft.destinations.map((destination, i) =>
                        i === index ? { ...destination, ...patch } : destination
                    ),
                }),
                removeDestination: (draft, { index }) => ({
                    ...draft,
                    destinations: draft.destinations.filter((_, i) => i !== index),
                }),
            },
        ],
    }),

    loaders(({ values }) => ({
        preview: [
            null as ErrorTrackingAlertPreviewApi | null,
            {
                loadPreview: async ({ trigger }: { trigger: TriggersEnumApi }, breakpoint) => {
                    await breakpoint(150)
                    // Project routes resolve to the root environment; name the active one so the
                    // sample issue comes from where the person actually works.
                    const environmentId = teamLogic.values.currentTeamId
                    const preview = await errorTrackingAlertsPreviewRetrieve(projectId(), {
                        trigger,
                        ...(environmentId ? { environment_id: environmentId } : {}),
                    })
                    breakpoint()
                    return preview
                },
            },
        ],
        saving: [
            false,
            {
                saveAlert: async () => {
                    const draft = values.draft
                    const payload = payloadFromDraft(draft)
                    if (draft.id) {
                        await errorTrackingAlertsUpdate(projectId(), draft.id, payload)
                    } else {
                        await errorTrackingAlertsCreate(projectId(), payload)
                    }
                    return true
                },
            },
        ],
        deleting: [
            false,
            {
                deleteAlert: async () => {
                    if (values.draft.id) {
                        await errorTrackingAlertsDestroy(projectId(), values.draft.id)
                    }
                    return true
                },
            },
        ],
    })),

    selectors({
        triggersCustomized: [
            (s) => [s.draft, s.customizingTriggers],
            (draft: AlertDraft, customizingTriggers: boolean): boolean =>
                customizingTriggers || !hasEveryTrigger(draft.triggers),
        ],
        primaryTrigger: [
            (s) => [s.draft],
            (draft: AlertDraft): TriggersEnumApi =>
                TRIGGER_OPTIONS.find((option) => draft.triggers.includes(option.value))?.value ?? 'issue_created',
        ],
        saveDisabledReason: [
            (s) => [s.draft],
            (draft: AlertDraft): string | null => {
                if (!draft.name.trim()) {
                    return 'Give the alert a name'
                }
                if (draft.triggers.length === 0) {
                    return 'Pick at least one event that starts a thread'
                }
                // An incomplete row would be dropped from the payload without a word, so block on it.
                // The one exception is a single untouched row: that is the fresh-alert state and
                // gets the plainer message below.
                const rows = draft.destinations.map((destination) => ({
                    hasWorkspace: destination.integrationId !== null,
                    hasChannel: splitChannel(destination.channel) !== null,
                }))
                const incomplete = rows.some((row) => !row.hasWorkspace || !row.hasChannel)
                const halfFilled = rows.some((row) => row.hasWorkspace !== row.hasChannel)
                if (incomplete && (rows.length > 1 || halfFilled)) {
                    return 'Pick a channel for every Slack destination, or remove the empty one'
                }
                if (payloadFromDraft(draft).destinations.length === 0) {
                    return 'Pick a Slack workspace and channel'
                }
                return null
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        openEditor: () => {
            actions.loadPreview({ trigger: values.primaryTrigger })
        },
        setTriggerEnabled: () => {
            actions.loadPreview({ trigger: values.primaryTrigger })
        },
        resetTriggers: () => {
            actions.loadPreview({ trigger: values.primaryTrigger })
        },
        saveAlertSuccess: () => {
            lemonToast.success(values.draft.id ? 'Alert updated' : 'Alert created')
            actions.closeEditor()
            actions.loadAlerts()
        },
        saveAlertFailure: ({ error }) => {
            lemonToast.error(error ? `Could not save the alert: ${error}` : 'Could not save the alert')
        },
        deleteAlertSuccess: () => {
            lemonToast.success('Alert deleted')
            actions.closeEditor()
            actions.loadAlerts()
        },
        deleteAlertFailure: () => {
            lemonToast.error('Could not delete the alert')
        },
    })),
])

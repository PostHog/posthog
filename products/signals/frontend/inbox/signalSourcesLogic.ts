import { MakeLogicType, actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { ApiConfig } from 'lib/api'
import type { PaginatedResponse } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { productEnablementCreate } from '~/generated/core/api'
import { ExternalDataSourceType } from '~/queries/schema/schema-general'
import { ExternalDataSource, ExternalDataSourceSchema, TeamPublicType, TeamType } from '~/types'

import { sourcesDataLogic } from 'products/data_warehouse/frontend/shared/logics/sourcesDataLogic'
import {
    engineeringAnalyticsCiSignalsConfigRetrieve,
    engineeringAnalyticsCiSignalsConfigUpdate,
} from 'products/engineering_analytics/frontend/generated/api'
import type { CISignalsConfigApi } from 'products/engineering_analytics/frontend/generated/api.schemas'
import { eventDefinitionsList } from 'products/event_definitions/frontend/generated/api'
import { visionScannersList, visionScannersPartialUpdate } from 'products/replay_vision/frontend/generated/api'
import type { ReplayScannerApi } from 'products/replay_vision/frontend/generated/api.schemas'
import { SignalSourceProduct, SignalSourceType } from 'products/signals/frontend/inbox/types'

import type { SignalSourceTypeApi } from '../generated/api.schemas'
import type { AgentRosterSource } from './components/config/agentRosterMeta'
import { captureSignalSourceConnected, captureSignalSourceDisabled } from './inboxAnalytics'
import { SignalSourceConfig, ToggleSignalSourceParams } from './types'

/** product_enablement recipe names for tools that back a signal source. */
export type SourceToolEnablement = 'session_replay' | 'error_tracking' | 'conversations'

export type SourceToolDataStatus = 'unavailable' | 'loading' | 'error' | 'recent' | 'none'

export interface SourceToolStatus {
    toolName: string
    enabled: boolean | null
    enablement: SourceToolEnablement | null
    dataStatus: SourceToolDataStatus
}

/** Event definitions probed to detect recent data for each source's tool. */
const TOOL_USAGE_EVENTS = ['$exception', '$ai_generation', '$ai_trace', '$pageview', '$autocapture']

/**
 * Cap on the per-source entity lists the roster inlines. Well past the tail: the busiest projects
 * run a few dozen scanners, and the median runs one.
 */
const ENTITY_PAGE_SIZE = 100

/** Matches Cymbal `EmitSignalRequest.source_type` + `products.signals.backend.api.emit_signal` checks. */
export const ERROR_TRACKING_SIGNAL_SOURCE_TYPES: SignalSourceType[] = [
    SignalSourceType.IssueCreated,
    SignalSourceType.IssueReopened,
    SignalSourceType.IssueSpiking,
]

/** Warehouse-backed signal sources, keyed by roster source id. */
export type WarehouseBackedSource = 'github' | 'linear' | 'zendesk' | 'pganalyze' | 'engineering_analytics'

type WarehouseSourceCompletion =
    | {
          kind: 'source_config'
          sourceProduct: SignalSourceProduct
          sourceType: SignalSourceType
          enableErrorMessage: string
      }
    | { kind: 'ci_signals_bundle' }

/**
 * One registration per warehouse-backed signal source: the warehouse product that backs it, the
 * tables its signals read (pre-selected in the wizard and forced to sync), and what enabling means
 * once connected. Keyed by signal source, not warehouse product — GitHub backs more than one source.
 */
export const WAREHOUSE_SOURCE_SETUP: Record<
    WarehouseBackedSource,
    {
        dwSourceType: ExternalDataSourceType
        requiredTables: string[]
        completion: WarehouseSourceCompletion
    }
> = {
    github: {
        dwSourceType: 'Github',
        requiredTables: ['issues'],
        completion: {
            kind: 'source_config',
            sourceProduct: SignalSourceProduct.Github,
            sourceType: SignalSourceType.Issue,
            enableErrorMessage: 'Failed to enable GitHub Issues',
        },
    },
    linear: {
        dwSourceType: 'Linear',
        requiredTables: ['issues'],
        completion: {
            kind: 'source_config',
            sourceProduct: SignalSourceProduct.Linear,
            sourceType: SignalSourceType.Issue,
            enableErrorMessage: 'Failed to enable Linear Issues',
        },
    },
    zendesk: {
        dwSourceType: 'Zendesk',
        requiredTables: ['tickets'],
        completion: {
            kind: 'source_config',
            sourceProduct: SignalSourceProduct.Zendesk,
            sourceType: SignalSourceType.Ticket,
            enableErrorMessage: 'Failed to enable Zendesk Tickets',
        },
    },
    pganalyze: {
        dwSourceType: 'PgAnalyze',
        requiredTables: ['issues', 'servers'],
        completion: {
            kind: 'source_config',
            sourceProduct: SignalSourceProduct.Pganalyze,
            sourceType: SignalSourceType.Issue,
            enableErrorMessage: 'Failed to enable pganalyze',
        },
    },
    engineering_analytics: {
        dwSourceType: 'Github',
        requiredTables: ['workflow_runs', 'pull_requests', 'workflow_jobs'],
        completion: { kind: 'ci_signals_bundle' },
    },
}

/** Values subset used by data-warehouse source helpers */
interface SignalSourcesLogicValuesForDw {
    sourceConfigs: SignalSourceConfig[] | null
}

function getWarehouseSourceConfig(
    values: SignalSourcesLogicValuesForDw,
    source: WarehouseBackedSource
): SignalSourceConfig | null {
    const { completion } = WAREHOUSE_SOURCE_SETUP[source]
    if (completion.kind !== 'source_config') {
        return null
    }
    return (
        values.sourceConfigs?.find(
            (c) => c.source_product === completion.sourceProduct && c.source_type === completion.sourceType
        ) ?? null
    )
}

function getWarehouseSourceToggleKey(source: WarehouseBackedSource): string | null {
    const { completion } = WAREHOUSE_SOURCE_SETUP[source]
    return completion.kind === 'source_config' ? `${completion.sourceProduct}_${completion.sourceType}` : null
}

function setSourceConfigState(
    state: SignalSourceConfig[] | null,
    sourceProduct: SignalSourceProduct,
    sourceType: SignalSourceType,
    enabled: boolean
): SignalSourceConfig[] | null {
    if (!state) {
        return state
    }
    const existing = state.find((c) => c.source_product === sourceProduct && c.source_type === sourceType)
    if (existing) {
        return state.map((c) =>
            c.source_product === sourceProduct && c.source_type === sourceType ? { ...c, enabled } : c
        )
    }
    if (!enabled) {
        return state
    }
    return [
        ...state,
        {
            id: `new_${sourceProduct}_${sourceType}`,
            source_product: sourceProduct,
            source_type: sourceType,
            enabled: true,
            config: {},
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            status: null,
        },
    ]
}

function toggleSourceConfigState(
    state: SignalSourceConfig[] | null,
    sourceProduct: SignalSourceProduct,
    sourceType: SignalSourceType
): SignalSourceConfig[] | null {
    const existing = state?.find((c) => c.source_product === sourceProduct && c.source_type === sourceType)
    return setSourceConfigState(state, sourceProduct, sourceType, !existing?.enabled)
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface signalSourcesLogicValues {
    featureFlags: FeatureFlagsSet // featureFlagLogic
    dataWarehouseSources: PaginatedResponse<ExternalDataSource> | null // sourcesDataLogic
    dataWarehouseSourcesLoading: boolean // sourcesDataLogic
    currentTeam: TeamPublicType | TeamType | null // teamLogic
    anomalyInvestigationConfig: SignalSourceConfig | null
    ciSignalsConfig: CISignalsConfigApi | null
    ciSignalsConfigLoading: boolean
    ciSignalsIsFullyEnabled: boolean
    conversationsConfig: SignalSourceConfig | null
    dataSourceSetupSource: WarehouseBackedSource | null
    enabledSourcesCount: number
    enablingTool: SourceToolEnablement | null
    errorTrackingIsFullyEnabled: boolean
    errorTrackingTypeStates: {
        enabled: boolean
        sourceType: SignalSourceType
    }[]
    evalReportsConfig: SignalSourceConfig | null
    githubIssuesConfig: SignalSourceConfig | null
    hasEmittingScanner: boolean | null
    hasNoSources: boolean
    healthChecksConfig: SignalSourceConfig | null
    isAnomalyInvestigationToggling: boolean
    isCiSignalsToggling: boolean
    isConversationsToggling: boolean
    isErrorTrackingToggling: boolean
    isEvalReportsToggling: boolean
    isGithubIssuesToggling: boolean
    isHealthChecksToggling: boolean
    isLinearIssuesToggling: boolean
    isPgAnalyzeIssuesToggling: boolean
    isZendeskTicketsToggling: boolean
    linearIssuesConfig: SignalSourceConfig | null
    pgAnalyzeIssuesConfig: SignalSourceConfig | null
    sourceConfigs: SignalSourceConfig[] | null
    sourceConfigsLoadFailed: boolean
    sourceConfigsLoading: boolean
    sourcesModalOpen: boolean
    togglingSourceKeys: Set<string>
    toolDataEvents: Set<string> | null
    toolDataEventsFailed: boolean
    toolDataEventsLoading: boolean
    toolStatusBySource: Partial<Record<AgentRosterSource, SourceToolStatus>>
    visionScanners: ReplayScannerApi[] | null
    visionScannersLoading: boolean
    zendeskTicketsConfig: SignalSourceConfig | null
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface signalSourcesLogicActions {
    loadSources: () => {
        value: true
    } // sourcesDataLogic
    closeDataSourceSetup: () => {
        value: true
    }
    closeSourcesModal: () => {
        value: true
    }
    completeDataWarehouseSourceToggle: (source: WarehouseBackedSource) => {
        source: WarehouseBackedSource
    }
    enableSourceTool: (enablement: SourceToolEnablement) => {
        enablement: SourceToolEnablement
    }
    enableSourceToolComplete: () => {
        value: true
    }
    initiateDataWarehouseSourceToggle: (source: WarehouseBackedSource) => {
        source: WarehouseBackedSource
    }
    loadCiSignalsConfig: () => any
    loadCiSignalsConfigFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadCiSignalsConfigSuccess: (
        ciSignalsConfig: CISignalsConfigApi,
        payload?: any
    ) => {
        ciSignalsConfig: CISignalsConfigApi
        payload?: any
    }
    loadSourceConfigs: () => any
    loadSourceConfigsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSourceConfigsSuccess: (
        sourceConfigs: SignalSourceConfig[],
        payload?: any
    ) => {
        sourceConfigs: SignalSourceConfig[]
        payload?: any
    }
    loadToolDataEvents: () => any
    loadToolDataEventsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadToolDataEventsSuccess: (
        toolDataEvents: Set<string>,
        payload?: any
    ) => {
        toolDataEvents: Set<string>
        payload?: any
    }
    loadVisionScanners: () => any
    loadVisionScannersFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadVisionScannersSuccess: (
        visionScanners: ReplayScannerApi[],
        payload?: any
    ) => {
        visionScanners: ReplayScannerApi[]
        payload?: any
    }
    onDataSourceSetupComplete: () => {
        value: true
    }
    openDataSourceSetup: (source: WarehouseBackedSource) => {
        source: WarehouseBackedSource
    }
    openSourcesModal: () => {
        value: true
    }
    replaceSourceConfig: (config: SignalSourceConfig) => {
        config: SignalSourceConfig
    }
    setAllScannerSignals: (enabled: boolean) => {
        enabled: boolean
    }
    setAllScannerSignalsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    setAllScannerSignalsSuccess: (
        visionScanners: ReplayScannerApi[],
        payload?: {
            enabled: boolean
        }
    ) => {
        visionScanners: ReplayScannerApi[]
        payload?: {
            enabled: boolean
        }
    }
    setDataWarehouseSourceEnabled: (
        source: WarehouseBackedSource,
        enabled: boolean
    ) => {
        enabled: boolean
        source: WarehouseBackedSource
    }
    startDataWarehouseSourceToggle: (source: WarehouseBackedSource) => {
        source: WarehouseBackedSource
    }
    toggleAnomalyInvestigation: () => {
        value: true
    }
    toggleCiSignals: (viaSetupWizard?: boolean) => {
        viaSetupWizard: boolean
    }
    toggleCiSignalsComplete: () => {
        value: true
    }
    toggleConversations: () => {
        value: true
    }
    toggleErrorTracking: () => {
        value: true
    }
    toggleErrorTrackingComplete: () => {
        value: true
    }
    toggleErrorTrackingType: (sourceType: SignalSourceType) => {
        sourceType: SignalSourceTypeApi
    }
    toggleEvalReports: () => {
        value: true
    }
    toggleHealthChecks: () => {
        value: true
    }
    toggleScannerSignals: ({ scannerId }: any) => any
    toggleScannerSignalsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    toggleScannerSignalsSuccess: (
        visionScanners: ReplayScannerApi[],
        payload?: any
    ) => {
        visionScanners: ReplayScannerApi[]
        payload?: any
    }
    toggleSignalSource: (params: ToggleSignalSourceParams) => {
        params: ToggleSignalSourceParams
    }
    toggleSignalSourceFailure: (
        params: ToggleSignalSourceParams,
        error: string
    ) => {
        error: string
        params: ToggleSignalSourceParams
    }
    toggleSignalSourceSuccess: (params: ToggleSignalSourceParams) => {
        params: ToggleSignalSourceParams
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface signalSourcesLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        githubIssuesConfig: (sourceConfigs: SignalSourceConfig[] | null) => SignalSourceConfig | null
        linearIssuesConfig: (sourceConfigs: SignalSourceConfig[] | null) => SignalSourceConfig | null
        zendeskTicketsConfig: (sourceConfigs: SignalSourceConfig[] | null) => SignalSourceConfig | null
        pgAnalyzeIssuesConfig: (sourceConfigs: SignalSourceConfig[] | null) => SignalSourceConfig | null
        conversationsConfig: (sourceConfigs: SignalSourceConfig[] | null) => SignalSourceConfig | null
        isConversationsToggling: (togglingSourceKeys: Set<string>) => boolean
        isGithubIssuesToggling: (togglingSourceKeys: Set<string>) => boolean
        isLinearIssuesToggling: (togglingSourceKeys: Set<string>) => boolean
        isZendeskTicketsToggling: (togglingSourceKeys: Set<string>) => boolean
        isPgAnalyzeIssuesToggling: (togglingSourceKeys: Set<string>) => boolean
        isErrorTrackingToggling: (togglingSourceKeys: Set<string>) => boolean
        healthChecksConfig: (sourceConfigs: SignalSourceConfig[] | null) => SignalSourceConfig | null
        isHealthChecksToggling: (togglingSourceKeys: Set<string>) => boolean
        evalReportsConfig: (sourceConfigs: SignalSourceConfig[] | null) => SignalSourceConfig | null
        isEvalReportsToggling: (togglingSourceKeys: Set<string>) => boolean
        anomalyInvestigationConfig: (sourceConfigs: SignalSourceConfig[] | null) => SignalSourceConfig | null
        isAnomalyInvestigationToggling: (togglingSourceKeys: Set<string>) => boolean
        toolStatusBySource: (
            currentTeam: TeamPublicType | TeamType | null,
            toolDataEvents: Set<string> | null,
            toolDataEventsLoading: boolean,
            toolDataEventsFailed: boolean
        ) => Partial<Record<AgentRosterSource, SourceToolStatus>>
        errorTrackingIsFullyEnabled: (sourceConfigs: SignalSourceConfig[] | null) => boolean
        ciSignalsIsFullyEnabled: (ciSignalsConfig: CISignalsConfigApi | null) => boolean
        isCiSignalsToggling: (togglingSourceKeys: Set<string>) => boolean
        hasEmittingScanner: (visionScanners: ReplayScannerApi[] | null) => boolean | null
        errorTrackingTypeStates: (sourceConfigs: SignalSourceConfig[] | null) => {
            enabled: boolean
            sourceType: SignalSourceType
        }[]
        enabledSourcesCount: (sourceConfigs: SignalSourceConfig[] | null, hasEmittingScanner: boolean | null) => number
        hasNoSources: (sourceConfigs: SignalSourceConfig[] | null, enabledSourcesCount: number) => boolean
    }
}

export type signalSourcesLogicType = MakeLogicType<
    signalSourcesLogicValues,
    signalSourcesLogicActions,
    Record<string, any>,
    signalSourcesLogicMeta
>

export const signalSourcesLogic = kea<signalSourcesLogicType>([
    path(['scenes', 'inbox', 'signalSourcesLogic']),

    connect(() => ({
        values: [
            sourcesDataLogic,
            ['dataWarehouseSources', 'dataWarehouseSourcesLoading'],
            featureFlagLogic,
            ['featureFlags'],
            teamLogic,
            ['currentTeam'],
        ],
        actions: [sourcesDataLogic, ['loadSources']],
    })),

    actions({
        openSourcesModal: true,
        closeSourcesModal: true,
        initiateDataWarehouseSourceToggle: (source: WarehouseBackedSource) => ({ source }),
        startDataWarehouseSourceToggle: (source: WarehouseBackedSource) => ({ source }),
        completeDataWarehouseSourceToggle: (source: WarehouseBackedSource) => ({ source }),
        setDataWarehouseSourceEnabled: (source: WarehouseBackedSource, enabled: boolean) => ({ source, enabled }),
        openDataSourceSetup: (source: WarehouseBackedSource) => ({ source }),
        closeDataSourceSetup: true,
        onDataSourceSetupComplete: true,
        toggleSignalSource: (params: ToggleSignalSourceParams) => ({ params }),
        toggleSignalSourceSuccess: (params: ToggleSignalSourceParams) => ({ params }),
        toggleSignalSourceFailure: (params: ToggleSignalSourceParams, error: string) => ({ params, error }),
        replaceSourceConfig: (config: SignalSourceConfig) => ({ config }),
        toggleErrorTracking: true,
        toggleErrorTrackingComplete: true,
        toggleErrorTrackingType: (sourceType: SignalSourceType) => ({ sourceType }),
        setAllScannerSignals: (enabled: boolean) => ({ enabled }),
        toggleCiSignals: (viaSetupWizard?: boolean) => ({ viaSetupWizard: viaSetupWizard ?? false }),
        toggleCiSignalsComplete: true,
        toggleHealthChecks: true,
        toggleEvalReports: true,
        toggleConversations: true,
        toggleAnomalyInvestigation: true,
        enableSourceTool: (enablement: SourceToolEnablement) => ({ enablement }),
        enableSourceToolComplete: true,
    }),

    loaders(({ values }) => ({
        sourceConfigs: [
            null as SignalSourceConfig[] | null,
            {
                loadSourceConfigs: async () => {
                    const response = await api.signalSourceConfigs.list()
                    return response.results
                },
            },
        ],
        ciSignalsConfig: [
            null as CISignalsConfigApi | null,
            {
                loadCiSignalsConfig: async (): Promise<CISignalsConfigApi> =>
                    engineeringAnalyticsCiSignalsConfigRetrieve(String(teamLogic.values.currentTeamId)),
            },
        ],
        toolDataEvents: [
            null as Set<string> | null,
            {
                loadToolDataEvents: async (): Promise<Set<string>> => {
                    const response = await eventDefinitionsList(String(teamLogic.values.currentTeamId), {
                        exclude_stale: true,
                        names: TOOL_USAGE_EVENTS,
                        limit: TOOL_USAGE_EVENTS.length,
                    })
                    return new Set(
                        response.results.filter(({ last_seen_at }) => !!last_seen_at).map(({ name }) => name)
                    )
                },
            },
        ],
        // Replay Vision never writes a `SignalSourceConfig` row: each scanner's own `emits_signals`
        // flag is the per-source authorization, so its roster row reads the scanners API instead.
        // `null` until the answer is in, so callers can tell "nothing there" from "not asked yet".
        visionScanners: [
            null as ReplayScannerApi[] | null,
            {
                loadVisionScanners: async (): Promise<ReplayScannerApi[]> => {
                    try {
                        // `ApiConfig` over `teamLogic.values.currentTeamId`: the team loads async, so
                        // on a cold mount the kea value is still null and the source reads as off.
                        const response = await visionScannersList(String(ApiConfig.getCurrentProjectId()), {
                            enabled: 'enabled',
                            limit: ENTITY_PAGE_SIZE,
                        })
                        return response.results
                    } catch {
                        // Replay Vision 404s when its flag is off, and this source only ever adds to
                        // the count, so a failure reads as "no scanners" rather than stranding every
                        // consumer of the count on a loading state.
                        return []
                    }
                },
                toggleScannerSignals: async ({ scannerId }): Promise<ReplayScannerApi[]> => {
                    const scanners = values.visionScanners ?? []
                    const scanner = scanners.find((existing: ReplayScannerApi) => existing.id === scannerId)
                    if (!scanner) {
                        return scanners
                    }
                    const updated = await visionScannersPartialUpdate(
                        String(ApiConfig.getCurrentProjectId()),
                        scannerId,
                        { emits_signals: !scanner.emits_signals }
                    )
                    return scanners.map((existing: ReplayScannerApi) =>
                        existing.id === scannerId ? updated : existing
                    )
                },
                // One action rather than N single toggles: each of those reads the same starting
                // list and returns a whole new one, so the last to land would drop the others.
                setAllScannerSignals: async ({ enabled }): Promise<ReplayScannerApi[]> => {
                    const scanners = values.visionScanners ?? []
                    const changing = scanners.filter(
                        (scanner: ReplayScannerApi) => (scanner.emits_signals ?? false) !== enabled
                    )
                    const updated = await Promise.all(
                        changing.map((scanner: ReplayScannerApi) =>
                            visionScannersPartialUpdate(String(ApiConfig.getCurrentProjectId()), scanner.id, {
                                emits_signals: enabled,
                            })
                        )
                    )
                    const byId = new Map(updated.map((scanner) => [scanner.id, scanner]))
                    return scanners.map((existing: ReplayScannerApi) => byId.get(existing.id) ?? existing)
                },
            },
        ],
    })),

    reducers({
        sourcesModalOpen: [
            false,
            {
                openSourcesModal: () => true,
                closeSourcesModal: () => false,
            },
        ],
        dataSourceSetupSource: [
            null as WarehouseBackedSource | null,
            {
                openDataSourceSetup: (_, { source }) => source,
                closeDataSourceSetup: () => null,
                closeSourcesModal: () => null,
            },
        ],
        enablingTool: [
            null as SourceToolEnablement | null,
            {
                enableSourceTool: (_, { enablement }) => enablement,
                enableSourceToolComplete: () => null,
            },
        ],
        toolDataEventsFailed: [
            false,
            {
                loadToolDataEvents: () => false,
                loadToolDataEventsSuccess: () => false,
                loadToolDataEventsFailure: () => true,
            },
        ],
        sourceConfigsLoadFailed: [
            false,
            {
                loadSourceConfigs: () => false,
                loadSourceConfigsSuccess: () => false,
                loadSourceConfigsFailure: () => true,
            },
        ],
        sourceConfigs: {
            // A save endpoint returned the row: reflect it immediately so consumers don't read
            // stale config while the follow-up list reload is in flight (or after it failed).
            replaceSourceConfig: (state: SignalSourceConfig[] | null, { config }: { config: SignalSourceConfig }) =>
                state ? state.map((c) => (c.id === config.id ? config : c)) : state,
            toggleHealthChecks: (state: SignalSourceConfig[] | null) =>
                toggleSourceConfigState(state, SignalSourceProduct.HealthChecks, SignalSourceType.HealthIssue),
            toggleEvalReports: (state: SignalSourceConfig[] | null) =>
                toggleSourceConfigState(state, SignalSourceProduct.LlmAnalytics, SignalSourceType.EvaluationReport),
            toggleConversations: (state: SignalSourceConfig[] | null) =>
                toggleSourceConfigState(state, SignalSourceProduct.Conversations, SignalSourceType.Ticket),
            toggleAnomalyInvestigation: (state: SignalSourceConfig[] | null) =>
                toggleSourceConfigState(state, SignalSourceProduct.Analytics, SignalSourceType.AnomalyInvestigation),
        },
        togglingSourceKeys: [
            new Set<string>(),
            {
                toggleSignalSource: (state, { params }) => {
                    const next = new Set(state)
                    next.add(`${params.sourceProduct}_${params.sourceType}`)
                    return next
                },
                toggleSignalSourceSuccess: (state, { params }) => {
                    const next = new Set(state)
                    next.delete(`${params.sourceProduct}_${params.sourceType}`)
                    return next
                },
                toggleSignalSourceFailure: (state, { params }) => {
                    const next = new Set(state)
                    next.delete(`${params.sourceProduct}_${params.sourceType}`)
                    return next
                },
                startDataWarehouseSourceToggle: (state, { source }) => {
                    const toggleKey = getWarehouseSourceToggleKey(source)
                    if (toggleKey === null) {
                        return state
                    }
                    const next = new Set(state)
                    next.add(toggleKey)
                    return next
                },
                completeDataWarehouseSourceToggle: (state, { source }) => {
                    const toggleKey = getWarehouseSourceToggleKey(source)
                    if (toggleKey === null) {
                        return state
                    }
                    const next = new Set(state)
                    next.delete(toggleKey)
                    return next
                },
                toggleErrorTracking: (state) => {
                    const next = new Set(state)
                    next.add('error_tracking')
                    return next
                },
                toggleErrorTrackingComplete: (state) => {
                    const next = new Set(state)
                    next.delete('error_tracking')
                    return next
                },
                toggleCiSignals: (state) => {
                    const next = new Set(state)
                    next.add('engineering_analytics')
                    return next
                },
                toggleCiSignalsComplete: (state) => {
                    const next = new Set(state)
                    next.delete('engineering_analytics')
                    return next
                },
            },
        ],
    }),

    selectors({
        githubIssuesConfig: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[] | null): SignalSourceConfig | null =>
                sourceConfigs?.find(
                    (c) => c.source_product === SignalSourceProduct.Github && c.source_type === SignalSourceType.Issue
                ) ?? null,
        ],
        linearIssuesConfig: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[] | null): SignalSourceConfig | null =>
                sourceConfigs?.find(
                    (c) => c.source_product === SignalSourceProduct.Linear && c.source_type === SignalSourceType.Issue
                ) ?? null,
        ],
        zendeskTicketsConfig: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[] | null): SignalSourceConfig | null =>
                sourceConfigs?.find(
                    (c) => c.source_product === SignalSourceProduct.Zendesk && c.source_type === SignalSourceType.Ticket
                ) ?? null,
        ],
        pgAnalyzeIssuesConfig: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[] | null): SignalSourceConfig | null =>
                sourceConfigs?.find(
                    (c) =>
                        c.source_product === SignalSourceProduct.Pganalyze && c.source_type === SignalSourceType.Issue
                ) ?? null,
        ],
        conversationsConfig: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[] | null): SignalSourceConfig | null =>
                sourceConfigs?.find(
                    (c) =>
                        c.source_product === SignalSourceProduct.Conversations &&
                        c.source_type === SignalSourceType.Ticket
                ) ?? null,
        ],
        isConversationsToggling: [
            (s) => [s.togglingSourceKeys],
            (keys: Set<string>): boolean => keys.has(`${SignalSourceProduct.Conversations}_${SignalSourceType.Ticket}`),
        ],
        isGithubIssuesToggling: [
            (s) => [s.togglingSourceKeys],
            (keys: Set<string>): boolean => keys.has(`${SignalSourceProduct.Github}_${SignalSourceType.Issue}`),
        ],
        isLinearIssuesToggling: [
            (s) => [s.togglingSourceKeys],
            (keys: Set<string>): boolean => keys.has(`${SignalSourceProduct.Linear}_${SignalSourceType.Issue}`),
        ],
        isZendeskTicketsToggling: [
            (s) => [s.togglingSourceKeys],
            (keys: Set<string>): boolean => keys.has(`${SignalSourceProduct.Zendesk}_${SignalSourceType.Ticket}`),
        ],
        isPgAnalyzeIssuesToggling: [
            (s) => [s.togglingSourceKeys],
            (keys: Set<string>): boolean => keys.has(`${SignalSourceProduct.Pganalyze}_${SignalSourceType.Issue}`),
        ],
        isErrorTrackingToggling: [
            (s) => [s.togglingSourceKeys],
            (keys: Set<string>): boolean => keys.has('error_tracking'),
        ],
        healthChecksConfig: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[] | null): SignalSourceConfig | null =>
                sourceConfigs?.find(
                    (c) =>
                        c.source_product === SignalSourceProduct.HealthChecks &&
                        c.source_type === SignalSourceType.HealthIssue
                ) ?? null,
        ],
        isHealthChecksToggling: [
            (s) => [s.togglingSourceKeys],
            (keys: Set<string>): boolean =>
                keys.has(`${SignalSourceProduct.HealthChecks}_${SignalSourceType.HealthIssue}`),
        ],
        evalReportsConfig: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[] | null): SignalSourceConfig | null =>
                sourceConfigs?.find(
                    (c) =>
                        c.source_product === SignalSourceProduct.LlmAnalytics &&
                        c.source_type === SignalSourceType.EvaluationReport
                ) ?? null,
        ],
        isEvalReportsToggling: [
            (s) => [s.togglingSourceKeys],
            (keys: Set<string>): boolean =>
                keys.has(`${SignalSourceProduct.LlmAnalytics}_${SignalSourceType.EvaluationReport}`),
        ],
        anomalyInvestigationConfig: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[] | null): SignalSourceConfig | null =>
                sourceConfigs?.find(
                    (c) =>
                        c.source_product === SignalSourceProduct.Analytics &&
                        c.source_type === SignalSourceType.AnomalyInvestigation
                ) ?? null,
        ],
        isAnomalyInvestigationToggling: [
            (s) => [s.togglingSourceKeys],
            (keys: Set<string>): boolean =>
                keys.has(`${SignalSourceProduct.Analytics}_${SignalSourceType.AnomalyInvestigation}`),
        ],
        toolStatusBySource: [
            (s) => [s.currentTeam, s.toolDataEvents, s.toolDataEventsLoading, s.toolDataEventsFailed],
            (
                currentTeam: TeamPublicType | TeamType | null,
                toolDataEvents: Set<string> | null,
                toolDataEventsLoading: boolean,
                toolDataEventsFailed: boolean
            ): Partial<Record<AgentRosterSource, SourceToolStatus>> => {
                const team = currentTeam as TeamType | null
                const dataStatus = (...events: string[]): SourceToolDataStatus => {
                    if (toolDataEventsLoading || (toolDataEvents === null && !toolDataEventsFailed)) {
                        return 'loading'
                    }
                    if (toolDataEventsFailed) {
                        return 'error'
                    }
                    return events.some((event) => toolDataEvents?.has(event)) ? 'recent' : 'none'
                }
                const errorTrackingDataStatus = dataStatus('$exception')
                const errorTrackingEnabled =
                    team?.autocapture_exceptions_opt_in === true || errorTrackingDataStatus === 'recent'
                        ? true
                        : team && errorTrackingDataStatus === 'none'
                          ? false
                          : null
                // Both replay sources read recordings, so they stand or fall on the same opt-in.
                const sessionReplayTool: SourceToolStatus = {
                    toolName: 'Session Replay',
                    enabled: team ? !!team.session_recording_opt_in : null,
                    enablement: 'session_replay',
                    // Recordings never produce event definitions, so there is no cheap signal.
                    dataStatus: 'unavailable',
                }
                return {
                    error_tracking: {
                        toolName: 'Error Tracking',
                        // Server SDKs capture exceptions without the autocapture opt-in, so recent
                        // exception data counts as on.
                        enabled: errorTrackingEnabled,
                        enablement: 'error_tracking',
                        dataStatus: errorTrackingDataStatus,
                    },
                    replay_vision: sessionReplayTool,
                    conversations: {
                        toolName: 'Support',
                        enabled: team ? !!team.conversations_enabled : null,
                        enablement: 'conversations',
                        dataStatus: 'unavailable',
                    },
                    llm_analytics: {
                        toolName: 'AI Observability',
                        enabled: true,
                        enablement: null,
                        dataStatus: dataStatus('$ai_generation', '$ai_trace'),
                    },
                    analytics: {
                        toolName: 'Product Analytics',
                        enabled: true,
                        enablement: null,
                        dataStatus: dataStatus('$pageview', '$autocapture'),
                    },
                }
            },
        ],
        errorTrackingIsFullyEnabled: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[] | null): boolean => {
                if (!sourceConfigs?.length) {
                    return false
                }
                return ERROR_TRACKING_SIGNAL_SOURCE_TYPES.every((sourceType) => {
                    const c = sourceConfigs.find(
                        (row) =>
                            row.source_product === SignalSourceProduct.ErrorTracking && row.source_type === sourceType
                    )
                    return c?.enabled === true
                })
            },
        ],
        ciSignalsIsFullyEnabled: [
            (s) => [s.ciSignalsConfig],
            (ciSignalsConfig: CISignalsConfigApi | null): boolean => ciSignalsConfig?.enabled ?? false,
        ],
        isCiSignalsToggling: [
            (s) => [s.togglingSourceKeys],
            (keys: Set<string>): boolean => keys.has('engineering_analytics'),
        ],
        // `null` until the scanners load, so callers can tell "no scanner emits" from "not asked yet".
        hasEmittingScanner: [
            (s) => [s.visionScanners],
            (visionScanners: ReplayScannerApi[] | null): boolean | null =>
                visionScanners === null ? null : visionScanners.some((scanner) => scanner.emits_signals),
        ],
        // Each error tracking signal type is its own config row, so each can be armed on its own.
        errorTrackingTypeStates: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[] | null): { sourceType: SignalSourceType; enabled: boolean }[] =>
                ERROR_TRACKING_SIGNAL_SOURCE_TYPES.map((sourceType) => ({
                    sourceType,
                    enabled:
                        sourceConfigs?.find(
                            (row) =>
                                row.source_product === SignalSourceProduct.ErrorTracking &&
                                row.source_type === sourceType
                        )?.enabled === true,
                })),
        ],
        enabledSourcesCount: [
            (s) => [s.sourceConfigs, s.hasEmittingScanner],
            // The scout gate is a meta-toggle surfaced in the Scout troop section, not a generic
            // signal source — exclude it so a scout-only project doesn't show the "Signal sources"
            // setup card as done with a phantom "1 watching". Replay Vision has no config row at
            // all, so it is counted separately, once, however many of its scanners emit.
            // Evaluation configs can survive from the retired per-result path, but eval reports are
            // the only AI observability source that emits signals.
            (sourceConfigs: SignalSourceConfig[] | null, hasEmittingScanner: boolean | null): number => {
                const configured =
                    sourceConfigs?.filter(
                        (c) =>
                            c.enabled &&
                            !(
                                c.source_product === SignalSourceProduct.SignalsScout &&
                                c.source_type === SignalSourceType.CrossSourceIssue
                            ) &&
                            !(
                                c.source_product === SignalSourceProduct.LlmAnalytics &&
                                c.source_type === SignalSourceType.Evaluation
                            ) &&
                            // Retired: rows survive until the cleanup migration runs, and counting
                            // them shows a watcher that cannot produce anything.
                            !(
                                c.source_product === SignalSourceProduct.SessionReplay &&
                                c.source_type === SignalSourceType.SessionAnalysisCluster
                            )
                    ).length ?? 0
                return configured + (hasEmittingScanner ? 1 : 0)
            },
        ],
        hasNoSources: [
            (s) => [s.sourceConfigs, s.enabledSourcesCount],
            (sourceConfigs: SignalSourceConfig[] | null, enabledSourcesCount: number): boolean =>
                sourceConfigs !== null && enabledSourcesCount === 0,
        ],
    }),

    listeners(({ actions, values }) => {
        // Cached list is null for a beat after mount (loadSources is debounced), so a toggle click
        // can beat it and misread it as "no source connected", opening the connect form and
        // duplicating a source. Fetch once as a fallback; on failure return empty so the caller
        // opens the connect form rather than hanging.
        async function currentWarehouseSources(): Promise<ExternalDataSource[]> {
            if (values.dataWarehouseSources !== null) {
                return values.dataWarehouseSources.results
            }
            try {
                return (await api.externalDataSources.list()).results
            } catch {
                return []
            }
        }

        // Enable any required table not yet syncing on the connected source. Multi-repo sources
        // qualify schema names (`owner/repo.endpoint`): match by suffix.
        async function ensureRequiredTableSyncing(
            sources: ExternalDataSource[],
            dwSourceType: string,
            tableName: string
        ): Promise<void> {
            const matchesTable = (schema: ExternalDataSourceSchema): boolean =>
                schema.name === tableName || schema.name.endsWith(`.${tableName}`)
            const schemas = sources
                .filter((source: ExternalDataSource) => source.source_type === dwSourceType)
                .flatMap((source: ExternalDataSource) => source.schemas ?? [])
                .filter((schema: ExternalDataSourceSchema) => matchesTable(schema) && !schema.should_sync)
            await Promise.all(
                schemas.map((schema: ExternalDataSourceSchema) =>
                    api.externalDataSchemas.update(schema.id, { should_sync: true })
                )
            )
        }

        return {
            loadCiSignalsConfigFailure: ({ error, errorObject }) => {
                // Silent failure would leave the card claiming setup is required for an armed source.
                lemonToast.error(errorObject?.detail || error || 'Failed to load CI signals status')
            },
            openSourcesModal: () => {
                // Load external data sources so we can check connectivity when user toggles a source
                actions.loadSources()
            },
            initiateDataWarehouseSourceToggle: async ({ source }) => {
                const { dwSourceType, requiredTables, completion } = WAREHOUSE_SOURCE_SETUP[source]
                const toggleKey = getWarehouseSourceToggleKey(source)
                if (
                    completion.kind !== 'source_config' ||
                    toggleKey === null ||
                    values.togglingSourceKeys.has(toggleKey)
                ) {
                    return
                }
                const sourceConfig = getWarehouseSourceConfig(values, source)
                const desiredEnabled = sourceConfig?.enabled !== true
                actions.startDataWarehouseSourceToggle(source)
                let downstreamToggleStarted = false
                try {
                    if (desiredEnabled) {
                        const sources = await currentWarehouseSources()
                        const hasSource = sources.some((s: ExternalDataSource) => s.source_type === dwSourceType)
                        if (!hasSource) {
                            actions.openDataSourceSetup(source)
                            return
                        }
                        for (const table of requiredTables) {
                            await ensureRequiredTableSyncing(sources, dwSourceType, table)
                        }
                    }
                    const currentConfig = getWarehouseSourceConfig(values, source)
                    if ((currentConfig?.enabled ?? false) === desiredEnabled) {
                        return
                    }
                    actions.setDataWarehouseSourceEnabled(source, desiredEnabled)
                    downstreamToggleStarted = true
                } catch (error: any) {
                    lemonToast.error(error?.detail || error?.message || completion.enableErrorMessage)
                } finally {
                    if (!downstreamToggleStarted) {
                        actions.completeDataWarehouseSourceToggle(source)
                    }
                }
            },
            onDataSourceSetupComplete: () => {
                const source = values.dataSourceSetupSource
                actions.closeDataSourceSetup()
                if (source === null) {
                    return
                }
                const { completion } = WAREHOUSE_SOURCE_SETUP[source]
                if (completion.kind === 'ci_signals_bundle') {
                    actions.toggleCiSignals(true)
                    return
                }
                actions.toggleSignalSource({
                    sourceProduct: completion.sourceProduct,
                    sourceType: completion.sourceType,
                    enabled: true,
                    viaSetupWizard: true,
                })
            },
            toggleSignalSource: async ({ params }, breakpoint) => {
                const { sourceProduct, sourceType, enabled, config } = params
                try {
                    const configs = values.sourceConfigs ?? []
                    const existing = configs.find(
                        (c: SignalSourceConfig) => c.source_product === sourceProduct && c.source_type === sourceType
                    )

                    if (existing && !existing.id.startsWith('new_')) {
                        const updateData: Partial<SignalSourceConfig> = { enabled }
                        if (config !== undefined) {
                            updateData.config = config
                        }
                        await api.signalSourceConfigs.update(existing.id, updateData)
                    } else if (enabled) {
                        await api.signalSourceConfigs.create({
                            source_product: sourceProduct,
                            source_type: sourceType,
                            enabled,
                            config: config ?? {},
                        })
                    }
                    breakpoint()
                    actions.toggleSignalSourceSuccess(params)
                    if (
                        sourceProduct === SignalSourceProduct.LlmAnalytics &&
                        sourceType === SignalSourceType.EvaluationReport
                    ) {
                        lemonToast.success(`AI observability signal source ${enabled ? 'enabled' : 'disabled'}`)
                    } else if (
                        sourceProduct === SignalSourceProduct.Analytics &&
                        sourceType === SignalSourceType.AnomalyInvestigation
                    ) {
                        lemonToast.success(`Product analytics signal source ${enabled ? 'enabled' : 'disabled'}`)
                    }
                    // Only a successful enable counts as a connection. First-time when there was no
                    // persisted (non-placeholder) config for this product/type before the toggle.
                    if (enabled) {
                        captureSignalSourceConnected({
                            sourceProduct,
                            sourceType,
                            isFirstConnection: !(existing && !existing.id.startsWith('new_')),
                            viaSetupWizard: params.viaSetupWizard ?? false,
                        })
                    } else {
                        captureSignalSourceDisabled({ sourceProduct, sourceType })
                    }
                    actions.loadSourceConfigs()
                } catch (error: any) {
                    breakpoint()
                    const errorMessage = error?.detail || error?.message || 'Failed to toggle signal source'
                    actions.toggleSignalSourceFailure(params, errorMessage)
                    actions.loadSourceConfigs()
                    lemonToast.error(errorMessage)
                }
            },
            toggleErrorTracking: async (_, breakpoint) => {
                // The row switch reads "on" as soon as one type is armed, so turning it off has to
                // stand every type down rather than arm the remaining ones.
                const desiredEnabled = !values.errorTrackingTypeStates.some(({ enabled }) => enabled)
                const configs = values.sourceConfigs ?? []
                // First connection when no persisted error-tracking config existed before this enable.
                const wasConnected = configs.some(
                    (c) => c.source_product === SignalSourceProduct.ErrorTracking && !c.id.startsWith('new_')
                )
                try {
                    for (const sourceType of ERROR_TRACKING_SIGNAL_SOURCE_TYPES) {
                        const existing = configs.find(
                            (c) =>
                                c.source_product === SignalSourceProduct.ErrorTracking && c.source_type === sourceType
                        )
                        if (existing && !existing.id.startsWith('new_')) {
                            await api.signalSourceConfigs.update(existing.id, { enabled: desiredEnabled })
                        } else if (desiredEnabled) {
                            await api.signalSourceConfigs.create({
                                source_product: SignalSourceProduct.ErrorTracking,
                                source_type: sourceType,
                                enabled: true,
                                config: {},
                            })
                        }
                    }
                    breakpoint()
                    actions.toggleErrorTrackingComplete()
                    if (desiredEnabled) {
                        captureSignalSourceConnected({
                            sourceProduct: SignalSourceProduct.ErrorTracking,
                            sourceType: SignalSourceType.IssueCreated,
                            isFirstConnection: !wasConnected,
                            viaSetupWizard: false,
                        })
                    } else {
                        captureSignalSourceDisabled({
                            sourceProduct: SignalSourceProduct.ErrorTracking,
                            sourceType: SignalSourceType.IssueCreated,
                        })
                    }
                    actions.loadSourceConfigs()
                } catch (error: any) {
                    breakpoint() // re-throws if superseded, skipping the lines below
                    actions.toggleErrorTrackingComplete()
                    const errorMessage = error?.detail || error?.message || 'Failed to toggle Error tracking signals'
                    lemonToast.error(errorMessage)
                    actions.loadSourceConfigs()
                }
            },
            toggleErrorTrackingType: async ({ sourceType }, breakpoint) => {
                const configs = values.sourceConfigs ?? []
                const existing = configs.find(
                    (c) => c.source_product === SignalSourceProduct.ErrorTracking && c.source_type === sourceType
                )
                const desiredEnabled = !(existing?.enabled ?? false)
                try {
                    if (existing && !existing.id.startsWith('new_')) {
                        await api.signalSourceConfigs.update(existing.id, { enabled: desiredEnabled })
                    } else if (desiredEnabled) {
                        await api.signalSourceConfigs.create({
                            source_product: SignalSourceProduct.ErrorTracking,
                            source_type: sourceType,
                            enabled: true,
                            config: {},
                        })
                    }
                    breakpoint()
                } catch (error: any) {
                    breakpoint()
                    lemonToast.error(error?.detail || error?.message || 'Failed to toggle this signal type')
                }
                actions.loadSourceConfigs()
            },
            toggleCiSignals: async ({ viaSetupWizard }, breakpoint) => {
                const desiredEnabled = !values.ciSignalsIsFullyEnabled
                const wasConnected = values.ciSignalsConfig?.configured ?? false
                // The setup wizard just connected GitHub with the CI tables preselected, so both
                // checks below would race the still-refreshing sources list — skip them.
                if (desiredEnabled && !viaSetupWizard) {
                    const sources = await currentWarehouseSources()
                    const hasGithubSource = sources.some((s: ExternalDataSource) => s.source_type === 'Github')
                    if (!hasGithubSource) {
                        actions.toggleCiSignalsComplete()
                        actions.openDataSourceSetup('engineering_analytics')
                        return
                    }
                    try {
                        const ciSetup = WAREHOUSE_SOURCE_SETUP.engineering_analytics
                        for (const tableName of ciSetup.requiredTables) {
                            await ensureRequiredTableSyncing(sources, ciSetup.dwSourceType, tableName)
                        }
                    } catch (error: any) {
                        actions.toggleCiSignalsComplete()
                        lemonToast.error(error?.detail || error?.message || 'Failed to enable GitHub CI signals')
                        return
                    }
                }
                try {
                    const updatedConfig = await engineeringAnalyticsCiSignalsConfigUpdate(
                        String(teamLogic.values.currentTeamId),
                        { enabled: desiredEnabled }
                    )
                    breakpoint()
                    actions.loadCiSignalsConfigSuccess(updatedConfig)
                    actions.toggleCiSignalsComplete()
                    if (desiredEnabled) {
                        captureSignalSourceConnected({
                            sourceProduct: SignalSourceProduct.EngineeringAnalytics,
                            sourceType: SignalSourceType.CiFlakyCheck,
                            isFirstConnection: !wasConnected,
                            viaSetupWizard,
                        })
                    } else {
                        captureSignalSourceDisabled({
                            sourceProduct: SignalSourceProduct.EngineeringAnalytics,
                            sourceType: SignalSourceType.CiFlakyCheck,
                        })
                    }
                    actions.loadSourceConfigs()
                } catch (error: any) {
                    breakpoint() // re-throws if superseded, skipping the lines below
                    actions.toggleCiSignalsComplete()
                    const errorMessage = error?.detail || error?.message || 'Failed to toggle GitHub CI signals'
                    lemonToast.error(errorMessage)
                    actions.loadCiSignalsConfig()
                    actions.loadSourceConfigs()
                }
            },
            toggleHealthChecks: () => {
                // The optimistic reducer flips the config before this listener runs,
                // so config.enabled already reflects the desired state.
                const config = values.healthChecksConfig
                const desiredEnabled = config?.enabled ?? true
                actions.toggleSignalSource({
                    sourceProduct: SignalSourceProduct.HealthChecks,
                    sourceType: SignalSourceType.HealthIssue,
                    enabled: desiredEnabled,
                })
            },
            toggleEvalReports: () => {
                // The optimistic reducer flips the config before this listener runs,
                // so config.enabled already reflects the desired state.
                const config = values.evalReportsConfig
                const desiredEnabled = config?.enabled ?? true
                actions.toggleSignalSource({
                    sourceProduct: SignalSourceProduct.LlmAnalytics,
                    sourceType: SignalSourceType.EvaluationReport,
                    enabled: desiredEnabled,
                })
            },
            toggleConversations: () => {
                // The optimistic reducer flips the config before this listener runs,
                // so config.enabled already reflects the desired state.
                const config = values.conversationsConfig
                const desiredEnabled = config?.enabled ?? true
                actions.toggleSignalSource({
                    sourceProduct: SignalSourceProduct.Conversations,
                    sourceType: SignalSourceType.Ticket,
                    enabled: desiredEnabled,
                })
            },
            toggleAnomalyInvestigation: () => {
                // The optimistic reducer flips the config before this listener runs,
                // so config.enabled already reflects the desired state.
                const config = values.anomalyInvestigationConfig
                const desiredEnabled = config?.enabled ?? true
                actions.toggleSignalSource({
                    sourceProduct: SignalSourceProduct.Analytics,
                    sourceType: SignalSourceType.AnomalyInvestigation,
                    enabled: desiredEnabled,
                })
            },
            enableSourceTool: async ({ enablement }) => {
                try {
                    await productEnablementCreate(String(teamLogic.values.currentTeamId), {
                        products: [enablement],
                    })
                    // Refresh the cached team so the tool reads back as on.
                    await teamLogic.asyncActions.loadCurrentTeam()
                } catch (error: any) {
                    lemonToast.error(error?.detail || error?.message || "Couldn't turn this on. Please try again.")
                } finally {
                    actions.enableSourceToolComplete()
                }
            },
            setDataWarehouseSourceEnabled: ({ source, enabled }) => {
                const { completion } = WAREHOUSE_SOURCE_SETUP[source]
                if (completion.kind !== 'source_config') {
                    return
                }
                actions.toggleSignalSource({
                    sourceProduct: completion.sourceProduct,
                    sourceType: completion.sourceType,
                    enabled,
                })
            },
        }
    }),

    events(({ actions, values }) => ({
        afterMount: () => {
            if (values.featureFlags[FEATURE_FLAGS.PRODUCT_AUTONOMY]) {
                // The condition allows us to safely mount this logic for user without the product autonomy feature flag
                // without needlessly loading the source configs
                actions.loadSourceConfigs()
                actions.loadVisionScanners()
                if (values.featureFlags[FEATURE_FLAGS.ENGINEERING_ANALYTICS]) {
                    actions.loadCiSignalsConfig()
                }
            }
        },
    })),
])

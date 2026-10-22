import { MakeLogicType, actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { combineUrl, router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { ApiConfig } from 'lib/api'
import type { PaginatedResponse } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { buildUserScopedPersistenceConfig } from 'lib/logic/persistence'
import { teamLogic } from 'scenes/teamLogic'

import { productEnablementCreate } from '~/generated/core/api'
import { ExternalDataSource, ExternalDataSourceSchema, IntegrationType, TeamPublicType, TeamType } from '~/types'

import { sourcesDataLogic } from 'products/data_warehouse/frontend/shared/logics/sourcesDataLogic'
import {
    engineeringAnalyticsCiSignalsConfigRetrieve,
    engineeringAnalyticsCiSignalsConfigUpdate,
} from 'products/engineering_analytics/frontend/generated/api'
import type { CISignalsConfigApi } from 'products/engineering_analytics/frontend/generated/api.schemas'
import { errorTrackingIssuesExistsRetrieve } from 'products/error_tracking/frontend/generated/api'
import { eventDefinitionsList } from 'products/event_definitions/frontend/generated/api'
import { visionScannersList, visionScannersPartialUpdate } from 'products/replay_vision/frontend/generated/api'
import type { ReplayScannerApi } from 'products/replay_vision/frontend/generated/api.schemas'
import { SignalSourceProduct, SignalSourceType } from 'products/signals/frontend/inbox/types'
import { externalDataSchemasPartialUpdate } from 'products/warehouse_sources/frontend/generated/api'
import { ExternalDataSourceTypeEnumApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { signalsOnboardingList } from '../generated/api'
import type {
    InboxOnboardingStateApi,
    SignalSourceTypeApi,
    SignalSourceConfigSourceTypeEnumApi,
} from '../generated/api.schemas'
import {
    AGENT_ROSTER_GROUPS,
    AgentRosterDefinition,
    AgentRosterGroup,
    AgentRosterSource,
} from './components/config/agentRosterMeta'
import { EXTERNAL_SIGNAL_SOURCES, ExternalSignalSource, isExternalSignalSource } from './externalSignalSources'
import {
    SignalSourceCatalogOrigin,
    SignalSourceToggleFailureReason,
    captureSignalSourceCatalogOpened,
    captureSignalSourceCatalogSourceSelected,
    captureSignalSourceConfigsLoadFailed,
    captureSignalSourceConnected,
    captureSignalSourceDisabled,
    captureSignalSourceToggleFailed,
} from './inboxAnalytics'
import {
    MAX_SOURCE_RECOMMENDATIONS,
    SourceRecommendation,
    SourceRecommendationInput,
    recommendSources,
} from './sourceRecommendations'
import { SOURCE_STEERING_KEY, SignalSourceConfig, SignalSourceConfigStatus, ToggleSignalSourceParams } from './types'

/** product_enablement recipe names for products that back a signal source. */
export type SourceProductEnablement = 'session_replay' | 'error_tracking' | 'conversations'

export type SourceProductDataStatus = 'unavailable' | 'loading' | 'error' | 'recent' | 'none'

export interface SourceProductStatus {
    productName: string
    enabled: boolean | null
    enablement: SourceProductEnablement | null
    dataStatus: SourceProductDataStatus
}

/** Event definitions probed to detect recent data for each source's product. */
const PRODUCT_USAGE_EVENTS = ['$exception', '$ai_generation', '$ai_trace', '$pageview', '$autocapture']

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

/**
 * The guidance written on the Error tracking card is stored on each of its signal-type rows, so a
 * row created later starts from what its siblings already carry. Without this, turning a type on
 * after writing guidance leaves that one trigger emitting unsteered while the card reads as set.
 */
function inheritedErrorTrackingConfig(configs: SignalSourceConfig[]): Record<string, any> {
    const steering = configs
        .map((config) => config.config[SOURCE_STEERING_KEY])
        .find((value) => typeof value === 'string' && value.trim())
    return steering ? { [SOURCE_STEERING_KEY]: steering } : {}
}

/** Warehouse-backed signal sources, keyed by roster source id. */
export type WarehouseBackedSource = ExternalSignalSource | 'engineering_analytics'

export const SOURCE_RECOMMENDATIONS_DISMISSAL_STORAGE_KEY = 'inbox-source-recommendations-dismissed'

const PINNED_SOURCE_ORDER: Partial<Record<AgentRosterSource, number>> = {
    github: 0,
    linear: 1,
    zendesk: 2,
    sentry: 3,
    jira: 4,
}

/** Catalog categories in the order the definitions list them, so the catalog reads like the registry. */
const CATALOG_CATEGORY_ORDER: readonly string[] = Array.from(
    new Set(
        AGENT_ROSTER_GROUPS.filter((group) => group.id === 'external')
            .flatMap((group) => group.agents)
            .map((agent) => agent.category)
            .filter((category): category is string => !!category)
    )
)

function compareExternalAgents(a: AgentRosterDefinition, b: AgentRosterDefinition): number {
    return (
        (PINNED_SOURCE_ORDER[a.source] ?? Number.MAX_SAFE_INTEGER) -
            (PINNED_SOURCE_ORDER[b.source] ?? Number.MAX_SAFE_INTEGER) || a.label.localeCompare(b.label)
    )
}

export interface SourceCatalogItem {
    agent: AgentRosterDefinition
    /** The warehouse already syncs this tool, so turning it on needs no connect form. */
    connected: boolean
    enabled: boolean
    syncFailed: boolean
    loading: boolean
    blockedReason?: string
}

export interface SourceCatalogGroup {
    category: string
    items: SourceCatalogItem[]
}

export interface ExternalSignalSourceState {
    config: SignalSourceConfig | null
    connected: boolean
    loading: boolean
    requiresSetup: boolean
    blockedReason?: string
}

/** Why the Linear teams picker is open: enabling the source (its save turns it on) or editing the filter. */
export interface LinearTeamsPickerState {
    enableOnSave: boolean
    viaSetupWizard: boolean
}

type WarehouseSourceCompletion =
    | {
          kind: 'source_config'
          sourceProduct: SignalSourceProduct
          sourceType: SignalSourceConfigSourceTypeEnumApi
          enableErrorMessage: string
      }
    | { kind: 'ci_signals_bundle' }

/**
 * One registration per warehouse-backed signal source: the warehouse product that backs it, the
 * tables its signals read (pre-selected in the wizard and forced to sync), and what enabling means
 * once connected. Keyed by signal source, not warehouse product — GitHub backs more than one source.
 */
interface WarehouseSourceSetup {
    dwSourceType: ExternalDataSourceTypeEnumApi
    requiredTables: string[]
    requiredTableSyncType?: 'full_refresh'
    completion: WarehouseSourceCompletion
}

export const WAREHOUSE_SOURCE_SETUP: Record<WarehouseBackedSource, WarehouseSourceSetup> = {
    ...(Object.fromEntries(
        EXTERNAL_SIGNAL_SOURCES.map((source): [ExternalSignalSource, WarehouseSourceSetup] => [
            source.source,
            {
                dwSourceType: source.dwSourceType,
                requiredTables: [...source.requiredTables],
                requiredTableSyncType: 'requiredTableSyncType' in source ? source.requiredTableSyncType : undefined,
                completion: {
                    kind: 'source_config',
                    sourceProduct: source.source,
                    sourceType: source.sourceType,
                    enableErrorMessage: `Failed to enable ${source.label}`,
                },
            },
        ])
    ) as Record<ExternalSignalSource, WarehouseSourceSetup>),
    engineering_analytics: {
        dwSourceType: 'Github',
        requiredTables: ['workflow_runs', 'pull_requests', 'workflow_jobs'],
        completion: { kind: 'ci_signals_bundle' },
    },
}

/**
 * Shown when a toggle runs before the source list has loaded. Without the list an existing source
 * looks new, and creating it again fails on the unique constraint with a message nobody can act on.
 */
const SOURCE_CONFIGS_UNAVAILABLE_MESSAGE = "Couldn't load your signal sources. Reload them and try again."

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
    integrations: IntegrationType[] | null // integrationsLogic
    integrationsLoading: boolean // integrationsLogic
    dataWarehouseSources: PaginatedResponse<ExternalDataSource> | null // sourcesDataLogic
    dataWarehouseSourcesLoading: boolean // sourcesDataLogic
    sourcesLoadError: boolean // sourcesDataLogic
    currentTeam: TeamPublicType | TeamType | null // teamLogic
    anomalyInvestigationConfig: SignalSourceConfig | null
    ciSignalsConfig: CISignalsConfigApi | null
    ciSignalsConfigLoading: boolean
    ciSignalsIsFullyEnabled: boolean
    conversationsConfig: SignalSourceConfig | null
    dataSourceSetupOAuthRedirectUrl: string | undefined
    dataSourceSetupSource: WarehouseBackedSource | null
    enabledSourcesCount: number
    enablingProduct: SourceProductEnablement | null
    errorTrackingConfigs: SignalSourceConfig[]
    errorTrackingHasIssues: boolean | null
    errorTrackingIsFullyEnabled: boolean
    errorTrackingTypeStates: {
        enabled: boolean
        sourceType: SignalSourceType
    }[]
    evalReportsConfig: SignalSourceConfig | null
    externalAgents: AgentRosterDefinition[]
    externalSourceCount: number
    externalSourceStates: Record<ExternalSignalSource, ExternalSignalSourceState>
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
    linearTeamsPicker: LinearTeamsPickerState | null
    onboardingState: InboxOnboardingStateApi | null
    onboardingStateLoading: boolean
    pgAnalyzeIssuesConfig: SignalSourceConfig | null
    productDataEvents: Set<string> | null
    productDataEventsFailed: boolean
    productDataEventsLoading: boolean
    productStatusBySource: Partial<Record<AgentRosterSource, SourceProductStatus>>
    recommendedSources: SourceRecommendation[]
    rosterGroups: AgentRosterGroup[]
    scannerInventoryKnown: boolean
    sourceCatalog: SourceCatalogGroup[]
    sourceCatalogOpen: boolean
    sourceCategory: string
    sourceCategoryOptions: {
        label: string
        value: string
    }[]
    sourceConfigs: SignalSourceConfig[] | null
    sourceConfigsLoadFailed: boolean
    sourceConfigsLoading: boolean
    sourceRecommendationsDismissal: string[] | null
    sourceSearchQuery: string
    sourcesModalOpen: boolean
    togglingSourceKeys: Set<string>
    visibleSourceRecommendations: SourceRecommendation[]
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
    closeLinearTeamsPicker: () => {
        value: true
    }
    closeSourceCatalog: () => {
        value: true
    }
    closeSourcesModal: () => {
        value: true
    }
    completeDataWarehouseSourceToggle: (source: WarehouseBackedSource) => {
        source: WarehouseBackedSource
    }
    enableSourceProduct: (enablement: SourceProductEnablement) => {
        enablement: SourceProductEnablement
    }
    enableSourceProductComplete: () => {
        value: true
    }
    hideSourceRecommendations: () => {
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
    loadOnboardingState: () => any
    loadOnboardingStateFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadOnboardingStateSuccess: (
        onboardingState: InboxOnboardingStateApi,
        payload?: any
    ) => {
        onboardingState: InboxOnboardingStateApi
        payload?: any
    }
    loadProductDataEvents: () => any
    loadProductDataEventsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadProductDataEventsSuccess: (
        productDataEvents: Set<string>,
        payload?: any
    ) => {
        productDataEvents: Set<string>
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
    openLinearTeamsPicker: (state: LinearTeamsPickerState) => LinearTeamsPickerState
    openSourceCatalog: () => {
        value: true
    }
    openSourcesModal: () => {
        value: true
    }
    replaceSourceConfig: (config: SignalSourceConfig) => {
        config: SignalSourceConfig
    }
    selectCatalogSource: (
        source: WarehouseBackedSource,
        origin: SignalSourceCatalogOrigin
    ) => {
        origin: SignalSourceCatalogOrigin
        source: WarehouseBackedSource
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
    setErrorTrackingHasIssues: (hasIssues: boolean | null) => {
        hasIssues: boolean | null
    }
    setScannerInventoryKnown: (known: boolean) => {
        known: boolean
    }
    setSourceCategory: (category: string) => {
        category: string
    }
    setSourceRecommendationsDismissed: (syncedSources: string[]) => {
        syncedSources: string[]
    }
    setSourceSearchQuery: (query: string) => {
        query: string
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
        dataSourceSetupOAuthRedirectUrl: (
            dataSourceSetupSource: WarehouseBackedSource | null,
            location: {
                hash: string
                pathname: string
                search: string
            },
            searchParams: Record<string, any>,
            hashParams: Record<string, any>
        ) => string | undefined
        externalSourceStates: (
            sourceConfigs: SignalSourceConfig[] | null,
            dataWarehouseSources: PaginatedResponse<ExternalDataSource> | null,
            sourcesLoadError: boolean,
            togglingSourceKeys: Set<string>
        ) => Record<ExternalSignalSource, ExternalSignalSourceState>
        externalAgents: (featureFlags: FeatureFlagsSet) => AgentRosterDefinition[]
        externalSourceCount: (externalAgents: AgentRosterDefinition[]) => number
        sourceCatalog: (
            externalAgents: AgentRosterDefinition[],
            sourceSearchQuery: string,
            sourceCategory: string,
            externalSourceStates: Record<
                | 'aha'
                | 'appfigures'
                | 'appfollow'
                | 'asknicely'
                | 'betterstack'
                | 'bigeye'
                | 'bugsnag'
                | 'canny'
                | 'dixa'
                | 'dynamics365'
                | 'featurebase'
                | 'firehydrant'
                | 'freshdesk'
                | 'freshservice'
                | 'frill'
                | 'front'
                | 'gitea'
                | 'github'
                | 'gitlab'
                | 'google_search_console'
                | 'gorgias'
                | 'grafana_irm'
                | 'honeybadger'
                | 'hubspot'
                | 'incident_io'
                | 'intercom'
                | 'jira'
                | 'judgeme_reviews'
                | 'kustomer'
                | 'linear'
                | 'monte_carlo'
                | 'opsgenie'
                | 'pagerduty'
                | 'pganalyze'
                | 'plain'
                | 'productboard'
                | 'rapid7_insightvm'
                | 'raygun'
                | 'retently'
                | 'rollbar'
                | 'semgrep'
                | 'sentry'
                | 'servicenow'
                | 'shortcut'
                | 'snyk'
                | 'solarwinds_service_desk'
                | 'sonarqube'
                | 'squadcast'
                | 'uservoice'
                | 'xmatters'
                | 'zendesk'
                | 'zoho_crm',
                ExternalSignalSourceState
            >,
            ciSignalsConfig: CISignalsConfigApi | null,
            ciSignalsIsFullyEnabled: boolean,
            isCiSignalsToggling: boolean,
            sourceConfigs: SignalSourceConfig[] | null,
            sourceConfigsLoading: boolean
        ) => SourceCatalogGroup[]
        sourceCategoryOptions: (externalAgents: AgentRosterDefinition[]) => {
            label: string
            value: string
        }[]
        rosterGroups: (
            featureFlags: FeatureFlagsSet,
            externalAgents: AgentRosterDefinition[],
            externalSourceStates: Record<
                | 'aha'
                | 'appfigures'
                | 'appfollow'
                | 'asknicely'
                | 'betterstack'
                | 'bigeye'
                | 'bugsnag'
                | 'canny'
                | 'dixa'
                | 'dynamics365'
                | 'featurebase'
                | 'firehydrant'
                | 'freshdesk'
                | 'freshservice'
                | 'frill'
                | 'front'
                | 'gitea'
                | 'github'
                | 'gitlab'
                | 'google_search_console'
                | 'gorgias'
                | 'grafana_irm'
                | 'honeybadger'
                | 'hubspot'
                | 'incident_io'
                | 'intercom'
                | 'jira'
                | 'judgeme_reviews'
                | 'kustomer'
                | 'linear'
                | 'monte_carlo'
                | 'opsgenie'
                | 'pagerduty'
                | 'pganalyze'
                | 'plain'
                | 'productboard'
                | 'rapid7_insightvm'
                | 'raygun'
                | 'retently'
                | 'rollbar'
                | 'semgrep'
                | 'sentry'
                | 'servicenow'
                | 'shortcut'
                | 'snyk'
                | 'solarwinds_service_desk'
                | 'sonarqube'
                | 'squadcast'
                | 'uservoice'
                | 'xmatters'
                | 'zendesk'
                | 'zoho_crm',
                ExternalSignalSourceState
            >,
            ciSignalsConfig: CISignalsConfigApi | null
        ) => AgentRosterGroup[]
        recommendedSources: (
            externalAgents: AgentRosterDefinition[],
            externalSourceStates: Record<
                | 'aha'
                | 'appfigures'
                | 'appfollow'
                | 'asknicely'
                | 'betterstack'
                | 'bigeye'
                | 'bugsnag'
                | 'canny'
                | 'dixa'
                | 'dynamics365'
                | 'featurebase'
                | 'firehydrant'
                | 'freshdesk'
                | 'freshservice'
                | 'frill'
                | 'front'
                | 'gitea'
                | 'github'
                | 'gitlab'
                | 'google_search_console'
                | 'gorgias'
                | 'grafana_irm'
                | 'honeybadger'
                | 'hubspot'
                | 'incident_io'
                | 'intercom'
                | 'jira'
                | 'judgeme_reviews'
                | 'kustomer'
                | 'linear'
                | 'monte_carlo'
                | 'opsgenie'
                | 'pagerduty'
                | 'pganalyze'
                | 'plain'
                | 'productboard'
                | 'rapid7_insightvm'
                | 'raygun'
                | 'retently'
                | 'rollbar'
                | 'semgrep'
                | 'sentry'
                | 'servicenow'
                | 'shortcut'
                | 'snyk'
                | 'solarwinds_service_desk'
                | 'sonarqube'
                | 'squadcast'
                | 'uservoice'
                | 'xmatters'
                | 'zendesk'
                | 'zoho_crm',
                ExternalSignalSourceState
            >,
            ciSignalsConfig: CISignalsConfigApi | null,
            ciSignalsIsFullyEnabled: boolean,
            integrations: IntegrationType[] | null,
            integrationsLoading: boolean,
            sourceConfigs: SignalSourceConfig[] | null,
            dataWarehouseSources: PaginatedResponse<ExternalDataSource> | null,
            sourcesLoadError: boolean,
            errorTrackingTypeStates: {
                enabled: boolean
                sourceType: SignalSourceType
            }[],
            conversationsConfig: SignalSourceConfig | null,
            onboardingState: InboxOnboardingStateApi | null,
            onboardingStateLoading: boolean
        ) => SourceRecommendation[]
        visibleSourceRecommendations: (
            recommendedSources: SourceRecommendation[],
            sourceRecommendationsDismissal: string[] | null
        ) => SourceRecommendation[]
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
        productStatusBySource: (
            currentTeam: TeamPublicType | TeamType | null,
            productDataEvents: Set<string> | null,
            productDataEventsLoading: boolean,
            productDataEventsFailed: boolean,
            errorTrackingHasIssues: boolean | null
        ) => Partial<Record<AgentRosterSource, SourceProductStatus>>
        errorTrackingIsFullyEnabled: (sourceConfigs: SignalSourceConfig[] | null) => boolean
        ciSignalsIsFullyEnabled: (ciSignalsConfig: CISignalsConfigApi | null) => boolean
        isCiSignalsToggling: (togglingSourceKeys: Set<string>) => boolean
        hasEmittingScanner: (visionScanners: ReplayScannerApi[] | null) => boolean | null
        errorTrackingConfigs: (sourceConfigs: SignalSourceConfig[] | null) => SignalSourceConfig[]
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
            ['dataWarehouseSources', 'dataWarehouseSourcesLoading', 'sourcesLoadError'],
            featureFlagLogic,
            ['featureFlags'],
            teamLogic,
            ['currentTeam'],
            integrationsLogic,
            ['integrations', 'integrationsLoading'],
        ],
        actions: [sourcesDataLogic, ['loadSources']],
    })),

    actions({
        setScannerInventoryKnown: (known: boolean) => ({ known }),
        setSourceSearchQuery: (query: string) => ({ query }),
        setSourceCategory: (category: string) => ({ category }),
        openSourceCatalog: true,
        closeSourceCatalog: true,
        selectCatalogSource: (source: WarehouseBackedSource, origin: SignalSourceCatalogOrigin) => ({
            source,
            origin,
        }),
        hideSourceRecommendations: true,
        setSourceRecommendationsDismissed: (syncedSources: string[]) => ({ syncedSources }),
        openSourcesModal: true,
        closeSourcesModal: true,
        initiateDataWarehouseSourceToggle: (source: WarehouseBackedSource) => ({ source }),
        startDataWarehouseSourceToggle: (source: WarehouseBackedSource) => ({ source }),
        completeDataWarehouseSourceToggle: (source: WarehouseBackedSource) => ({ source }),
        setDataWarehouseSourceEnabled: (source: WarehouseBackedSource, enabled: boolean) => ({ source, enabled }),
        openDataSourceSetup: (source: WarehouseBackedSource) => ({ source }),
        closeDataSourceSetup: true,
        onDataSourceSetupComplete: true,
        openLinearTeamsPicker: (state: LinearTeamsPickerState) => state,
        closeLinearTeamsPicker: true,
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
        enableSourceProduct: (enablement: SourceProductEnablement) => ({ enablement }),
        enableSourceProductComplete: true,
        setErrorTrackingHasIssues: (hasIssues: boolean | null) => ({ hasIssues }),
    }),

    loaders(({ values, actions }) => ({
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
        // Read here rather than from inboxSetupLogic: that logic depends on this one and drags the whole
        // setup flow in with it, and the recommendations only need the completion time.
        onboardingState: [
            null as InboxOnboardingStateApi | null,
            {
                loadOnboardingState: async (): Promise<InboxOnboardingStateApi> =>
                    signalsOnboardingList(String(ApiConfig.getCurrentProjectId())),
            },
        ],
        productDataEvents: [
            null as Set<string> | null,
            {
                loadProductDataEvents: async (): Promise<Set<string>> => {
                    const projectId = String(ApiConfig.getCurrentProjectId())
                    const [response, issues] = await Promise.all([
                        eventDefinitionsList(projectId, {
                            exclude_stale: true,
                            names: PRODUCT_USAGE_EVENTS,
                            limit: PRODUCT_USAGE_EVENTS.length,
                        }),
                        errorTrackingIssuesExistsRetrieve(projectId).catch(() => null),
                    ])
                    actions.setErrorTrackingHasIssues(issues?.exists ?? null)
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
                        actions.setScannerInventoryKnown(!response.next)
                        return response.results
                    } catch {
                        actions.setScannerInventoryKnown(false)
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

    reducers(() => ({
        scannerInventoryKnown: [false, { setScannerInventoryKnown: (_, { known }) => known }],
        errorTrackingHasIssues: [
            null as boolean | null,
            { setErrorTrackingHasIssues: (_, { hasIssues }) => hasIssues },
        ],
        sourceSearchQuery: ['', { setSourceSearchQuery: (_, { query }) => query, closeSourceCatalog: () => '' }],
        sourceCategory: ['', { setSourceCategory: (_, { category }) => category, closeSourceCatalog: () => '' }],
        // The connect form is a step inside the catalog, so resuming one after OAuth reopens the catalog
        // around it. The Linear teams picker is a modal of its own, so the catalog yields to it.
        sourceCatalogOpen: [
            false,
            {
                openSourceCatalog: () => true,
                openDataSourceSetup: () => true,
                closeSourceCatalog: () => false,
                openLinearTeamsPicker: () => false,
                closeSourcesModal: () => false,
            },
        ],
        // Remember existing synced sources so only a new connection can undo a dismissal.
        sourceRecommendationsDismissal: [
            null as string[] | null,
            { ...buildUserScopedPersistenceConfig(), storageKey: SOURCE_RECOMMENDATIONS_DISMISSAL_STORAGE_KEY },
            { setSourceRecommendationsDismissed: (_, { syncedSources }) => syncedSources },
        ],
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
                closeSourceCatalog: () => null,
                closeSourcesModal: () => null,
            },
        ],
        linearTeamsPicker: [
            null as LinearTeamsPickerState | null,
            {
                openLinearTeamsPicker: (_, state) => state,
                closeLinearTeamsPicker: () => null,
                closeSourcesModal: () => null,
            },
        ],
        enablingProduct: [
            null as SourceProductEnablement | null,
            {
                enableSourceProduct: (_, { enablement }) => enablement,
                enableSourceProductComplete: () => null,
            },
        ],
        productDataEventsFailed: [
            false,
            {
                loadProductDataEvents: () => false,
                loadProductDataEventsSuccess: () => false,
                loadProductDataEventsFailure: () => true,
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
    })),

    selectors({
        dataSourceSetupOAuthRedirectUrl: [
            (s) => [
                s.dataSourceSetupSource,
                router.selectors.location,
                router.selectors.searchParams,
                router.selectors.hashParams,
            ],
            (
                source: WarehouseBackedSource | null,
                location: ReturnType<typeof router.selectors.location>,
                searchParams: Record<string, unknown>,
                hashParams: Record<string, unknown>
            ): string | undefined =>
                source
                    ? combineUrl(
                          location.pathname,
                          { ...searchParams, setup: 'signal-sources', signal_source: source },
                          hashParams
                      ).url
                    : undefined,
        ],
        externalSourceStates: [
            (s) => [s.sourceConfigs, s.dataWarehouseSources, s.sourcesLoadError, s.togglingSourceKeys],
            (
                sourceConfigs: SignalSourceConfig[] | null,
                warehouseSources: PaginatedResponse<ExternalDataSource> | null,
                warehouseError: boolean,
                togglingKeys: Set<string>
            ): Record<ExternalSignalSource, ExternalSignalSourceState> =>
                Object.fromEntries(
                    EXTERNAL_SIGNAL_SOURCES.map((source) => {
                        const config =
                            sourceConfigs?.find(
                                (row) => row.source_product === source.source && row.source_type === source.sourceType
                            ) ?? null
                        const connected =
                            warehouseSources?.results.some(
                                (connection) => connection.source_type === source.dwSourceType
                            ) ?? false
                        return [
                            source.source,
                            {
                                config,
                                connected,
                                loading:
                                    togglingKeys.has(`${source.source}_${source.sourceType}`) ||
                                    (warehouseSources === null && !warehouseError),
                                requiresSetup: warehouseSources !== null && !connected && !config?.enabled,
                                blockedReason:
                                    warehouseSources === null && warehouseError
                                        ? "Couldn't load connections. Select Retry above to try again."
                                        : undefined,
                            },
                        ]
                    })
                ) as Record<ExternalSignalSource, ExternalSignalSourceState>,
        ],
        externalAgents: [
            (s) => [s.featureFlags],
            (featureFlags: FeatureFlagsSet): AgentRosterDefinition[] =>
                AGENT_ROSTER_GROUPS.filter((group) => group.id === 'external')
                    .flatMap((group) => group.agents)
                    .filter((agent) => !agent.flag || featureFlags[agent.flag])
                    .sort(compareExternalAgents),
        ],
        externalSourceCount: [(s) => [s.externalAgents], (agents: AgentRosterDefinition[]): number => agents.length],
        sourceCatalog: [
            (s) => [
                s.externalAgents,
                s.sourceSearchQuery,
                s.sourceCategory,
                s.externalSourceStates,
                s.ciSignalsConfig,
                s.ciSignalsIsFullyEnabled,
                s.isCiSignalsToggling,
                s.sourceConfigs,
                s.sourceConfigsLoading,
            ],
            (
                agents: AgentRosterDefinition[],
                query: string,
                category: string,
                externalStates: Record<ExternalSignalSource, ExternalSignalSourceState>,
                ciConfig: CISignalsConfigApi | null,
                ciEnabled: boolean,
                ciToggling: boolean,
                sourceConfigs: SignalSourceConfig[] | null,
                sourceConfigsLoading: boolean
            ): SourceCatalogGroup[] => {
                const needle = query.trim().toLowerCase()
                // Without the config rows a synced tool reads as never turned on, and a click would
                // create a row that may already exist, so every tile that writes one waits.
                const configsBlockedReason =
                    sourceConfigs !== null
                        ? undefined
                        : sourceConfigsLoading
                          ? 'Loading your signal sources'
                          : "Couldn't load your signal sources. Close this and select Retry."
                const items = agents
                    .filter(
                        (agent) =>
                            (!category || agent.category === category) &&
                            `${agent.label} ${agent.category ?? ''} ${agent.watches}`.toLowerCase().includes(needle)
                    )
                    .map((agent): SourceCatalogItem => {
                        if (isExternalSignalSource(agent.source)) {
                            const state = externalStates[agent.source]
                            return {
                                agent,
                                connected: state.connected,
                                enabled: !!state.config?.enabled,
                                syncFailed: state.config?.status === SignalSourceConfigStatus.FAILED,
                                loading: state.loading,
                                blockedReason: state.blockedReason ?? configsBlockedReason,
                            }
                        }
                        return {
                            agent,
                            connected: !!ciConfig?.configured,
                            enabled: ciEnabled,
                            syncFailed: ciConfig?.sync_status === 'failed',
                            loading: ciToggling,
                        }
                    })
                return CATALOG_CATEGORY_ORDER.map((groupCategory) => ({
                    category: groupCategory,
                    items: items.filter((item) => item.agent.category === groupCategory),
                })).filter((group) => group.items.length > 0)
            },
        ],
        sourceCategoryOptions: [
            (s) => [s.externalAgents],
            (agents: AgentRosterDefinition[]): { label: string; value: string }[] => [
                { label: 'All categories', value: '' },
                ...CATALOG_CATEGORY_ORDER.filter((category) => agents.some((agent) => agent.category === category)).map(
                    (category) => ({ label: category, value: category })
                ),
            ],
        ],
        rosterGroups: [
            (s) => [s.featureFlags, s.externalAgents, s.externalSourceStates, s.ciSignalsConfig],
            (
                featureFlags: FeatureFlagsSet,
                externalAgents: AgentRosterDefinition[],
                externalStates: Record<ExternalSignalSource, ExternalSignalSourceState>,
                ciConfig: CISignalsConfigApi | null
            ): AgentRosterGroup[] =>
                AGENT_ROSTER_GROUPS.map((group) => ({
                    ...group,
                    agents:
                        group.id === 'external'
                            ? externalAgents.filter((agent) =>
                                  isExternalSignalSource(agent.source)
                                      ? externalStates[agent.source].connected ||
                                        !!externalStates[agent.source].config?.enabled
                                      : !!ciConfig?.configured
                              )
                            : group.agents.filter((agent) => !agent.flag || featureFlags[agent.flag]),
                })),
        ],
        // A recommendation built before configs, connections, and integrations finish loading can
        // tell someone to connect a tool they already use.
        recommendedSources: [
            (s) => [
                s.externalAgents,
                s.externalSourceStates,
                s.ciSignalsConfig,
                s.ciSignalsIsFullyEnabled,
                s.integrations,
                s.integrationsLoading,
                s.sourceConfigs,
                s.dataWarehouseSources,
                s.sourcesLoadError,
                s.errorTrackingTypeStates,
                s.conversationsConfig,
                s.onboardingState,
                s.onboardingStateLoading,
            ],
            (
                agents: AgentRosterDefinition[],
                externalStates: Record<ExternalSignalSource, ExternalSignalSourceState>,
                ciConfig: CISignalsConfigApi | null,
                ciEnabled: boolean,
                integrations: IntegrationType[] | null,
                integrationsLoading: boolean,
                sourceConfigs: SignalSourceConfig[] | null,
                dataWarehouseSources: PaginatedResponse<ExternalDataSource> | null,
                sourcesLoadError: boolean,
                errorTrackingTypeStates: { enabled: boolean; sourceType: SignalSourceType }[],
                conversationsConfig: SignalSourceConfig | null,
                onboardingState: InboxOnboardingStateApi | null,
                onboardingStateLoading: boolean
            ): SourceRecommendation[] => {
                if (
                    sourceConfigs === null ||
                    (integrations === null && integrationsLoading) ||
                    (dataWarehouseSources === null && !sourcesLoadError) ||
                    (onboardingState === null && onboardingStateLoading)
                ) {
                    return []
                }
                const completedChoices = onboardingState?.completed_at ? (onboardingState.draft?.sources ?? []) : []
                const declinedInOnboarding = (source: WarehouseBackedSource): boolean => {
                    const choices = completedChoices.filter((choice) => choice.source_product === source)
                    return choices.length > 0 && choices.every((choice) => !choice.enabled)
                }
                const states: SourceRecommendationInput[] = [
                    {
                        source: 'error_tracking',
                        connected: false,
                        enabled: errorTrackingTypeStates.some(({ enabled }) => enabled),
                    },
                    { source: 'conversations', connected: false, enabled: !!conversationsConfig?.enabled },
                    ...agents.map((agent): SourceRecommendationInput => {
                        if (isExternalSignalSource(agent.source)) {
                            const state = externalStates[agent.source]
                            return {
                                source: agent.source,
                                connected: state.connected,
                                enabled: !!state.config?.enabled,
                                declinedInOnboarding: state.connected && declinedInOnboarding(agent.source),
                            }
                        }
                        return {
                            source: agent.source,
                            connected: !!ciConfig?.configured,
                            enabled: ciEnabled,
                            declinedInOnboarding:
                                !!ciConfig?.configured && declinedInOnboarding(agent.source as WarehouseBackedSource),
                        }
                    }),
                ]
                return recommendSources(
                    agents,
                    states,
                    (integrations ?? []).map((integration) => integration.kind)
                )
            },
        ],
        // Hidden means hidden, except for a tool synced after the person hid the strip: a fresh
        // warehouse connection is the strongest hint the strip ever has.
        visibleSourceRecommendations: [
            (s) => [s.recommendedSources, s.sourceRecommendationsDismissal],
            (recommendations: SourceRecommendation[], dismissal: string[] | null): SourceRecommendation[] =>
                (dismissal === null
                    ? recommendations
                    : recommendations.filter(
                          (recommendation) =>
                              recommendation.reason === 'synced' && !dismissal.includes(recommendation.agent.source)
                      )
                ).slice(0, MAX_SOURCE_RECOMMENDATIONS),
        ],
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
        productStatusBySource: [
            (s) => [
                s.currentTeam,
                s.productDataEvents,
                s.productDataEventsLoading,
                s.productDataEventsFailed,
                s.errorTrackingHasIssues,
            ],
            (
                currentTeam: TeamPublicType | TeamType | null,
                productDataEvents: Set<string> | null,
                productDataEventsLoading: boolean,
                productDataEventsFailed: boolean,
                errorTrackingHasIssues: boolean | null
            ): Partial<Record<AgentRosterSource, SourceProductStatus>> => {
                const team = currentTeam as TeamType | null
                const dataStatus = (...events: string[]): SourceProductDataStatus => {
                    if (productDataEvents === null && (productDataEventsLoading || !productDataEventsFailed)) {
                        return 'loading'
                    }
                    if (productDataEventsFailed) {
                        return 'error'
                    }
                    return events.some((event) => productDataEvents?.has(event)) ? 'recent' : 'none'
                }
                const exceptionEventStatus = dataStatus('$exception')
                const errorTrackingDataStatus =
                    errorTrackingHasIssues && exceptionEventStatus !== 'recent'
                        ? 'unavailable'
                        : exceptionEventStatus === 'none' && errorTrackingHasIssues === null
                          ? 'error'
                          : exceptionEventStatus
                const errorTrackingEnabled =
                    team?.autocapture_exceptions_opt_in === true ||
                    errorTrackingHasIssues === true ||
                    errorTrackingDataStatus === 'recent'
                        ? true
                        : team && errorTrackingDataStatus === 'none'
                          ? false
                          : null
                // Both replay sources read recordings, so they stand or fall on the same opt-in.
                const sessionReplayProduct: SourceProductStatus = {
                    productName: 'Session replay',
                    enabled: team ? !!team.session_recording_opt_in : null,
                    enablement: 'session_replay',
                    // Recordings never produce event definitions, so there is no cheap signal.
                    dataStatus: 'unavailable',
                }
                return {
                    error_tracking: {
                        productName: 'Error tracking',
                        // Server SDKs and manually captured exceptions do not require browser autocapture.
                        enabled: errorTrackingEnabled,
                        enablement: 'error_tracking',
                        dataStatus: errorTrackingDataStatus,
                    },
                    replay_vision: sessionReplayProduct,
                    conversations: {
                        productName: 'Support',
                        enabled: team ? !!team.conversations_enabled : null,
                        enablement: 'conversations',
                        dataStatus: 'unavailable',
                    },
                    llm_analytics: {
                        productName: 'AI observability',
                        enabled: true,
                        enablement: null,
                        dataStatus: dataStatus('$ai_generation', '$ai_trace'),
                    },
                    analytics: {
                        productName: 'Product analytics',
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
        // The rows behind the one Error tracking card. Guidance written on the card is saved to all
        // of them, since a reader steering "error tracking" means the source, not one trigger.
        errorTrackingConfigs: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[] | null): SignalSourceConfig[] =>
                ERROR_TRACKING_SIGNAL_SOURCE_TYPES.map((sourceType) =>
                    sourceConfigs?.find(
                        (row) =>
                            row.source_product === SignalSourceProduct.ErrorTracking && row.source_type === sourceType
                    )
                ).filter((row): row is SignalSourceConfig => !!row),
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
        // duplicating a source. A failed lookup leaves connectivity unknown, so it must not open
        // another connection form.
        async function currentWarehouseSources(): Promise<ExternalDataSource[]> {
            if (values.dataWarehouseSources !== null) {
                return values.dataWarehouseSources.results
            }
            try {
                return (await api.externalDataSources.list()).results
            } catch {
                throw new Error("Couldn't load your connections. Retry before connecting a new source.")
            }
        }

        // Enable any required table not yet syncing on the connected source. Multi-repo sources
        // qualify schema names (`owner/repo.endpoint`): match by suffix.
        async function ensureRequiredTableSyncing(
            sources: ExternalDataSource[],
            dwSourceType: string,
            tableName: string,
            fullRefresh: boolean = false
        ): Promise<void> {
            const matchesTable = (schema: ExternalDataSourceSchema): boolean =>
                schema.name === tableName || schema.name.endsWith(`.${tableName}`)
            const matchingSchemas = sources
                .filter((source: ExternalDataSource) => source.source_type === dwSourceType)
                .flatMap((source: ExternalDataSource) => source.schemas ?? [])
                .filter(matchesTable)
            if (matchingSchemas.length === 0) {
                throw new Error(
                    dwSourceType === 'GoogleSearchConsole'
                        ? 'This connection is missing web search data. Add the Web search type to your Google Search Console connection in Data warehouse, then try again.'
                        : `Required table not found: ${tableName}. Update this connection in Data warehouse, then try again.`
                )
            }
            const schemas = matchingSchemas.filter(
                (schema) => !schema.should_sync || (fullRefresh && schema.sync_type !== 'full_refresh')
            )
            await Promise.all(
                schemas.map((schema: ExternalDataSourceSchema) =>
                    externalDataSchemasPartialUpdate(String(ApiConfig.getCurrentProjectId()), schema.id, {
                        should_sync: true,
                        ...(fullRefresh ? { sync_type: 'full_refresh' } : {}),
                    })
                )
            )
        }

        function failSignalSourceToggle(
            sourceProduct: SignalSourceProduct,
            sourceType: SignalSourceType,
            enabled: boolean,
            errorMessage: string,
            reason: SignalSourceToggleFailureReason
        ): void {
            captureSignalSourceToggleFailed({ sourceProduct, sourceType, enabled, reason, errorMessage })
            lemonToast.error(errorMessage)
            actions.loadSourceConfigs()
        }

        function forgetResumedSetup(): void {
            const { signal_source: source, ...searchParams } = router.values.searchParams
            if (source !== undefined) {
                router.actions.replace(router.values.location.pathname, searchParams, router.values.hashParams)
            }
        }

        return {
            closeDataSourceSetup: forgetResumedSetup,
            closeSourceCatalog: forgetResumedSetup,
            openSourceCatalog: () => {
                captureSignalSourceCatalogOpened({
                    recommendationCount: values.visibleSourceRecommendations.length,
                    connectedCount: values.rosterGroups.find((group) => group.id === 'external')?.agents.length ?? 0,
                })
            },
            hideSourceRecommendations: () => {
                actions.setSourceRecommendationsDismissed(
                    values.recommendedSources
                        .filter((recommendation) => recommendation.reason === 'synced')
                        .map((recommendation) => recommendation.agent.source)
                )
            },
            selectCatalogSource: ({ source, origin }) => {
                const reason = values.recommendedSources.find(
                    (recommendation) => recommendation.agent.source === source
                )?.reason
                captureSignalSourceCatalogSourceSelected({ source, origin, reason: reason ?? null })
                if (isExternalSignalSource(source)) {
                    actions.initiateDataWarehouseSourceToggle(source)
                } else {
                    actions.toggleCiSignals()
                }
            },
            // A source that turned on from the catalog shows up in the roster, so the catalog gets out of
            // the way. A connect form stays: its own completion closes the catalog below.
            toggleSignalSourceSuccess: ({ params }) => {
                if (params.enabled && values.sourceCatalogOpen && values.dataSourceSetupSource === null) {
                    actions.closeSourceCatalog()
                }
            },
            loadCiSignalsConfigSuccess: ({ ciSignalsConfig }) => {
                if (ciSignalsConfig.enabled && values.sourceCatalogOpen && values.dataSourceSetupSource === null) {
                    actions.closeSourceCatalog()
                }
            },
            loadSourceConfigs: () => {
                if (!values.onboardingStateLoading) {
                    actions.loadOnboardingState()
                }
            },
            loadSourceConfigsFailure: ({ error, errorObject }) => {
                captureSignalSourceConfigsLoadFailed(errorObject?.detail || error || 'Failed to load signal sources')
            },
            loadCiSignalsConfigFailure: ({ error, errorObject }) => {
                // Silent failure would leave the card claiming setup is required for an armed source.
                lemonToast.error(errorObject?.detail || error || 'Failed to load CI signals status')
            },
            openSourcesModal: () => {
                // Load external data sources so we can check connectivity when user toggles a source
                actions.loadSources()
            },
            initiateDataWarehouseSourceToggle: async ({ source }) => {
                const { dwSourceType, requiredTables, requiredTableSyncType, completion } =
                    WAREHOUSE_SOURCE_SETUP[source]
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
                            await ensureRequiredTableSyncing(
                                sources,
                                dwSourceType,
                                table,
                                requiredTableSyncType === 'full_refresh'
                            )
                        }
                    }
                    const currentConfig = getWarehouseSourceConfig(values, source)
                    if ((currentConfig?.enabled ?? false) === desiredEnabled) {
                        return
                    }
                    // Linear asks which teams to read before it turns on; the picker's save does the toggle.
                    if (source === 'linear' && desiredEnabled) {
                        actions.openLinearTeamsPicker({ enableOnSave: true, viaSetupWizard: false })
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
                actions.closeSourceCatalog()
                actions.loadSources()
                if (source === null) {
                    return
                }
                const { completion } = WAREHOUSE_SOURCE_SETUP[source]
                if (completion.kind === 'ci_signals_bundle') {
                    actions.toggleCiSignals(true)
                    return
                }
                if (source === 'linear') {
                    actions.openLinearTeamsPicker({ enableOnSave: true, viaSetupWizard: true })
                    return
                }
                actions.toggleSignalSource({
                    sourceProduct: completion.sourceProduct,
                    sourceType: completion.sourceType,
                    enabled: true,
                    viaSetupWizard: true,
                })
            },
            // No breakpoint here: every call settles its own source, and a breakpoint would let a
            // toggle on another source cancel this one, leaving its spinner up and its error unshown.
            toggleSignalSource: async ({ params }) => {
                const { sourceProduct, sourceType, enabled, config } = params
                if (values.sourceConfigs === null) {
                    actions.toggleSignalSourceFailure(params, SOURCE_CONFIGS_UNAVAILABLE_MESSAGE)
                    failSignalSourceToggle(
                        sourceProduct,
                        sourceType,
                        enabled,
                        SOURCE_CONFIGS_UNAVAILABLE_MESSAGE,
                        'configs_unavailable'
                    )
                    return
                }
                try {
                    const configs = values.sourceConfigs
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
                    const errorMessage = error?.detail || error?.message || 'Failed to toggle signal source'
                    actions.toggleSignalSourceFailure(params, errorMessage)
                    failSignalSourceToggle(sourceProduct, sourceType, enabled, errorMessage, 'request_failed')
                }
            },
            toggleErrorTracking: async (_, breakpoint) => {
                // The row switch reads "on" as soon as one type is armed, so turning it off has to
                // stand every type down rather than arm the remaining ones.
                const desiredEnabled = !values.errorTrackingTypeStates.some(({ enabled }) => enabled)
                if (values.sourceConfigs === null) {
                    actions.toggleErrorTrackingComplete()
                    failSignalSourceToggle(
                        SignalSourceProduct.ErrorTracking,
                        SignalSourceType.IssueCreated,
                        desiredEnabled,
                        SOURCE_CONFIGS_UNAVAILABLE_MESSAGE,
                        'configs_unavailable'
                    )
                    return
                }
                const configs = values.sourceConfigs
                const inheritedConfig = inheritedErrorTrackingConfig(values.errorTrackingConfigs)
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
                                config: inheritedConfig,
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
                    failSignalSourceToggle(
                        SignalSourceProduct.ErrorTracking,
                        SignalSourceType.IssueCreated,
                        desiredEnabled,
                        errorMessage,
                        'request_failed'
                    )
                }
            },
            // No breakpoint here either: each signal type is its own row, so a click on another type
            // must not cancel this one or swallow its error.
            toggleErrorTrackingType: async ({ sourceType }) => {
                const configs = values.sourceConfigs
                if (configs === null) {
                    failSignalSourceToggle(
                        SignalSourceProduct.ErrorTracking,
                        sourceType,
                        true,
                        SOURCE_CONFIGS_UNAVAILABLE_MESSAGE,
                        'configs_unavailable'
                    )
                    return
                }
                const inheritedConfig = inheritedErrorTrackingConfig(values.errorTrackingConfigs)
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
                            config: inheritedConfig,
                        })
                    }
                } catch (error: any) {
                    failSignalSourceToggle(
                        SignalSourceProduct.ErrorTracking,
                        sourceType,
                        desiredEnabled,
                        error?.detail || error?.message || 'Failed to toggle this signal type',
                        'request_failed'
                    )
                    return
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
            enableSourceProduct: async ({ enablement }) => {
                try {
                    await productEnablementCreate(String(teamLogic.values.currentTeamId), {
                        products: [enablement],
                    })
                    // Refresh the cached team so the product reads back as on.
                    await teamLogic.asyncActions.loadCurrentTeam()
                } catch (error: any) {
                    lemonToast.error(error?.detail || error?.message || "Couldn't turn this on. Please try again.")
                } finally {
                    actions.enableSourceProductComplete()
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
            const source = router.values.searchParams.signal_source
            if (
                router.values.searchParams.setup === 'signal-sources' &&
                typeof source === 'string' &&
                isExternalSignalSource(source)
            ) {
                actions.openDataSourceSetup(source)
            }
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

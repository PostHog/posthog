import { urls } from 'scenes/urls'

import type {
    ExternalDataSourceSerializersApi,
    ExternalDataSchemaApi,
} from 'products/warehouse_sources/frontend/generated/api.schemas'

import type { InboxOnboardingDraftApi, InboxOnboardingSourceApi } from '../../generated/api.schemas'
import { AGENT_ROSTER_GROUPS, AgentRosterDefinition } from '../components/config/agentRosterMeta'
import { WAREHOUSE_SOURCE_SETUP, type SourceProductStatus, type WarehouseBackedSource } from '../signalSourcesLogic'
import { SignalSourceProduct, SignalSourceType, type SignalSourceConfig } from '../types'

export interface InboxSetupSource {
    definition: AgentRosterDefinition
    sources: InboxOnboardingSourceApi[]
    available: boolean
    unavailableReason: string
    warehouseSource: WarehouseBackedSource | null
    setupUrl: string | null
}

interface InboxSetupWarehouseSource extends Pick<ExternalDataSourceSerializersApi, 'id' | 'source_type'> {
    schemas?: readonly Pick<ExternalDataSchemaApi, 'name'>[]
}

const SOURCE_TYPES: Partial<Record<string, InboxOnboardingSourceApi['source_type'][]>> = {
    error_tracking: [SignalSourceType.IssueCreated, SignalSourceType.IssueReopened, SignalSourceType.IssueSpiking],
    conversations: [SignalSourceType.Ticket],
    llm_analytics: [SignalSourceType.EvaluationReport],
    analytics: [SignalSourceType.AnomalyInvestigation],
    health_checks: [SignalSourceType.HealthIssue],
    engineering_analytics: [
        SignalSourceType.CiFlakyCheck,
        SignalSourceType.CiBrokenDefaultBranch,
        SignalSourceType.CiDurationRegression,
    ],
}

export function setupSources(
    configs: SignalSourceConfig[],
    statuses: Partial<Record<string, SourceProductStatus>>,
    scannerCount: number,
    flags: Record<string, boolean | string | undefined>,
    hasEvents: boolean,
    warehouseSources: readonly InboxSetupWarehouseSource[] | null = null
): InboxSetupSource[] {
    return AGENT_ROSTER_GROUPS.flatMap((group) => group.agents)
        .filter(
            (definition) =>
                !definition.legacy && definition.source !== 'pganalyze' && (!definition.flag || flags[definition.flag])
        )
        .map((definition) => {
            const existing = configs.filter((config) => config.source_product === definition.sourceProduct)
            const status = statuses[definition.source]
            const warehouseSource = Object.hasOwn(WAREHOUSE_SOURCE_SETUP, definition.source)
                ? (definition.source as WarehouseBackedSource)
                : null
            const warehouseSetup = warehouseSource ? WAREHOUSE_SOURCE_SETUP[warehouseSource] : null
            const connectedSources =
                warehouseSources?.filter((source) => source.source_type === warehouseSetup?.dwSourceType) ?? []
            const hasRequiredTables =
                !!warehouseSetup &&
                warehouseSetup.requiredTables.every((table) =>
                    connectedSources.some((source) =>
                        source.schemas?.some((schema) => schema.name === table || schema.name.endsWith(`.${table}`))
                    )
                )
            const setupUrl =
                connectedSources.length && !hasRequiredTables
                    ? urls.dataWarehouseSource(connectedSources[0].id, 'schemas')
                    : null
            const available =
                definition.source === 'replay_vision'
                    ? scannerCount > 0
                    : warehouseSetup && warehouseSources !== null
                      ? hasRequiredTables
                      : definition.source === 'health_checks'
                        ? hasEvents
                        : status
                          ? status.enabled === true &&
                            (status.dataStatus === 'recent' || status.dataStatus === 'unavailable')
                          : existing.length > 0
            const types =
                SOURCE_TYPES[definition.source] ??
                (warehouseSetup?.completion.kind === 'source_config'
                    ? [warehouseSetup.completion.sourceType]
                    : existing.map((config) => config.source_type as InboxOnboardingSourceApi['source_type']))
            return {
                definition,
                warehouseSource,
                setupUrl,
                available: available && (types.length > 0 || definition.source === 'replay_vision'),
                unavailableReason: setupUrl
                    ? 'Needs tables'
                    : status?.dataStatus === 'error'
                      ? 'Could not check data'
                      : definition.source === 'replay_vision' && status?.enabled
                        ? 'No scanners'
                        : status?.enabled === false
                          ? 'Not enabled'
                          : status
                            ? 'No recent data'
                            : definition.source === 'health_checks'
                              ? 'No data yet'
                              : 'Not connected',
                sources: types.map((source_type) => ({
                    source_product: definition.sourceProduct,
                    source_type,
                    enabled: true,
                })),
            }
        })
}

export function newInboxSetupDraft(sources: InboxSetupSource[], scannerIds: string[]): InboxOnboardingDraftApi {
    return {
        step: 'signals',
        sources: sources.filter((source) => source.available).flatMap((source) => source.sources),
        scanner_ids: scannerIds,
        suggestions: [],

        automatic_implementation: false,
        implementation_priority: 'P1',
    }
}

export function reconcileInboxSetupDraft(
    draft: InboxOnboardingDraftApi,
    sources: InboxSetupSource[],
    scannerIds: string[] | null = null
): InboxOnboardingDraftApi {
    const chosenProducts = new Set(draft.sources.map((source) => source.source_product))
    const newSources = sources
        .filter((source) => source.available && !chosenProducts.has(source.definition.sourceProduct))
        .flatMap((source) => source.sources)
    const availableScanners = scannerIds === null ? null : new Set(scannerIds)
    const selectedScanners = availableScanners
        ? draft.scanner_ids.filter((id) => availableScanners.has(id))
        : draft.scanner_ids
    return newSources.length || selectedScanners.length !== draft.scanner_ids.length
        ? { ...draft, sources: [...draft.sources, ...newSources], scanner_ids: selectedScanners }
        : draft
}

export function selectedSourceCount(draft: InboxOnboardingDraftApi): number {
    return new Set([
        ...draft.sources.filter((source) => source.enabled).map((source) => source.source_product),
        ...(draft.scanner_ids.length ? [SignalSourceProduct.ReplayVision] : []),
    ]).size
}

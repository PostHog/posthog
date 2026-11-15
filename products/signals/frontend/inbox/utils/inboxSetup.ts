import type { InboxOnboardingDraftApi, InboxOnboardingSourceApi } from '../../generated/api.schemas'
import { AGENT_ROSTER_GROUPS, AgentRosterDefinition } from '../components/config/agentRosterMeta'
import type { SourceProductStatus } from '../signalSourcesLogic'
import { SignalSourceProduct, SignalSourceType, type SignalSourceConfig } from '../types'

export interface InboxSetupSource {
    definition: AgentRosterDefinition
    sources: InboxOnboardingSourceApi[]
    available: boolean
    unavailableReason: string
}

const SOURCE_TYPES: Partial<Record<string, InboxOnboardingSourceApi['source_type'][]>> = {
    error_tracking: [SignalSourceType.IssueCreated, SignalSourceType.IssueReopened, SignalSourceType.IssueSpiking],
    conversations: [SignalSourceType.Ticket],
    llm_analytics: [SignalSourceType.EvaluationReport],
    analytics: [SignalSourceType.AnomalyInvestigation],
    health_checks: [SignalSourceType.HealthIssue],
}

// Onboarding offers PostHog products only. Warehouse-backed sources are connected from the Configuration tab after activation.
const ONBOARDING_ROSTER_AGENTS: readonly AgentRosterDefinition[] = AGENT_ROSTER_GROUPS.filter(
    (group) => group.id === 'posthog'
).flatMap((group) => group.agents)

export const ONBOARDING_SOURCE_PRODUCTS: ReadonlySet<string> = new Set(
    ONBOARDING_ROSTER_AGENTS.map((definition) => definition.sourceProduct)
)

export function setupSources(
    configs: SignalSourceConfig[],
    statuses: Partial<Record<string, SourceProductStatus>>,
    scannerCount: number,
    hasEvents: boolean
): InboxSetupSource[] {
    return ONBOARDING_ROSTER_AGENTS.map((definition) => {
        const existing = configs.filter((config) => config.source_product === definition.sourceProduct)
        const status = statuses[definition.source]
        const available =
            definition.source === 'replay_vision'
                ? scannerCount > 0
                : definition.source === 'health_checks'
                  ? hasEvents
                  : status
                    ? status.enabled === true && (status.dataStatus === 'recent' || status.dataStatus === 'unavailable')
                    : existing.length > 0
        const types =
            SOURCE_TYPES[definition.source] ??
            existing.map((config) => config.source_type as InboxOnboardingSourceApi['source_type'])
        return {
            definition,
            available: available && (types.length > 0 || definition.source === 'replay_vision'),
            unavailableReason:
                status?.dataStatus === 'error'
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
        setup_mode: 'guided',
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
    // A draft saved before onboarding became PostHog-only can still carry a warehouse-backed source.
    const keptSources = draft.sources.filter((source) => ONBOARDING_SOURCE_PRODUCTS.has(source.source_product))
    const chosenProducts = new Set(keptSources.map((source) => source.source_product))
    const newSources = sources
        .filter((source) => source.available && !chosenProducts.has(source.definition.sourceProduct))
        .flatMap((source) => source.sources)
    const availableScanners = scannerIds === null ? null : new Set(scannerIds)
    const selectedScanners = availableScanners
        ? draft.scanner_ids.filter((id) => availableScanners.has(id))
        : draft.scanner_ids
    return newSources.length ||
        keptSources.length !== draft.sources.length ||
        selectedScanners.length !== draft.scanner_ids.length
        ? { ...draft, sources: [...keptSources, ...newSources], scanner_ids: selectedScanners }
        : draft
}

export function selectedSourceCount(draft: InboxOnboardingDraftApi): number {
    return new Set([
        ...draft.sources.filter((source) => source.enabled).map((source) => source.source_product),
        ...(draft.scanner_ids.length ? [SignalSourceProduct.ReplayVision] : []),
    ]).size
}

import { useActions, useValues } from 'kea'
import { memo, useCallback, useMemo, useState } from 'react'

import { IconArrowUpRight, IconChevronRight, IconPlus } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonSkeleton,
    LemonSwitch,
    LemonTag,
    Link,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { LemonTagType } from 'lib/lemon-ui/LemonTag/LemonTag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { SyncStatusEnumApi } from 'products/engineering_analytics/frontend/generated/api.schemas'

import { signalSourcesLogic } from '../../signalSourcesLogic'
import type { SourceToolStatus } from '../../signalSourcesLogic'
import { SignalSourceConfig, SignalSourceConfigStatus, SignalSourceType } from '../../types'
import { getSourceProductMeta } from '../badges/sourceProductIcons'
import { AGENT_ROSTER_GROUPS, AgentRosterDefinition, AgentRosterSource } from './agentRosterMeta'

type AgentRosterStatus = 'standby' | 'watching' | 'syncing' | 'sync_failed'

/** Copy for the three error tracking signal types, which are enum values rather than named records. */
const ERROR_TRACKING_TYPE_LABELS: Partial<Record<string, { name: string; detail: string }>> = {
    [SignalSourceType.IssueCreated]: {
        name: 'New issue',
        detail: 'An error that has not been seen before.',
    },
    [SignalSourceType.IssueReopened]: {
        name: 'Reopened issue',
        detail: 'A resolved issue that came back.',
    },
    [SignalSourceType.IssueSpiking]: {
        name: 'Spiking issue',
        detail: 'A known issue whose rate jumped above its baseline.',
    },
}

/** Above this many entities the list gets a filter box rather than only a scroll bar. */
const ENTITY_FILTER_THRESHOLD = 8

function resolveAgentStatus(
    armed: boolean,
    syncStatus: SignalSourceConfigStatus | SyncStatusEnumApi | null | undefined
): AgentRosterStatus {
    if (syncStatus === SignalSourceConfigStatus.FAILED) {
        return 'sync_failed'
    }
    if (!armed) {
        return 'standby'
    }
    if (syncStatus === SignalSourceConfigStatus.RUNNING) {
        return 'syncing'
    }
    return 'watching'
}

/** One individually switchable thing inside a source: a scanner, an evaluation, a signal type. */
interface RosterEntity {
    id: string
    name: string
    detail?: string
    kind?: string
    enabled: boolean
}

/** Per-source derived state assembled by `AgentsRoster` from `signalSourcesLogic`. */
interface AgentSourceState {
    armed: boolean
    loading: boolean
    /** True for data-warehouse sources that haven't been connected yet – shows a Connect button. */
    requiresSetup: boolean
    syncStatus: SignalSourceConfigStatus | SyncStatusEnumApi | null | undefined
    entities: RosterEntity[]
    /** The entity list is still loading, so the count would read as a wrong zero. */
    entitiesLoading: boolean
}

function AgentIcon({ source }: { source: AgentRosterDefinition }): JSX.Element | null {
    const meta = getSourceProductMeta(source.sourceProduct)
    if (!meta?.Icon) {
        return null
    }
    const Icon = meta.Icon
    return <Icon className={`shrink-0 text-base ${meta.colorClass}`} />
}

function StatusDot({
    status,
    tool,
    toolOff,
}: {
    status: AgentRosterStatus
    tool?: SourceToolStatus
    toolOff: boolean
}): JSX.Element {
    let className = 'bg-border-bold'
    let title = 'Standby'
    if (toolOff) {
        title = `${tool?.toolName} is off, so this source has nothing to read`
    } else if (status === 'sync_failed') {
        className = 'bg-danger'
        title = 'Sync failed'
    } else if (status === 'syncing') {
        className = 'bg-accent'
        title = 'Syncing'
    } else if (status === 'watching') {
        // A hollow dot means watching but nothing has arrived, so the two read apart at a glance.
        className = tool?.receivingData === false ? 'border border-success' : 'bg-success'
        title =
            tool?.receivingData === false
                ? 'Watching, no data yet'
                : tool?.receivingData
                  ? 'Watching, receiving data'
                  : 'Watching'
    }
    return (
        <Tooltip title={title}>
            <span className={`size-2 shrink-0 rounded-full ${className}`} />
        </Tooltip>
    )
}

/** Only the states worth interrupting a scan for. Everything healthy shows no tag at all. */
function notableTag(
    status: AgentRosterStatus,
    armed: boolean,
    toolOff: boolean,
    tool?: SourceToolStatus
): { label: string; type: LemonTagType } | null {
    if (toolOff) {
        return { label: 'Tool off', type: 'warning' }
    }
    if (status === 'sync_failed') {
        return { label: 'Sync failed', type: 'danger' }
    }
    if (status === 'syncing') {
        return { label: 'Syncing', type: 'primary' }
    }
    if (armed && tool?.receivingData === false) {
        return { label: 'No data yet', type: 'muted' }
    }
    return null
}

function EntityRow({
    entity,
    onToggle,
    disabledReason,
}: {
    entity: RosterEntity
    onToggle: () => void
    disabledReason?: string
}): JSX.Element {
    return (
        <div className="flex items-center gap-2 px-2 py-1 hover:bg-surface-secondary">
            <LemonSwitch
                size="xxsmall"
                checked={entity.enabled}
                onChange={onToggle}
                disabledReason={disabledReason}
                aria-label={entity.name}
            />
            <span
                className={`max-w-60 shrink-0 truncate text-xs font-medium ${
                    entity.enabled ? 'text-default' : 'text-muted'
                }`}
            >
                {entity.name}
            </span>
            {entity.kind && (
                <LemonTag size="small" type="muted">
                    {entity.kind}
                </LemonTag>
            )}
            <span className="min-w-0 flex-1 truncate text-xs text-muted">{entity.detail}</span>
        </div>
    )
}

interface ExpansionProps {
    agent: AgentRosterDefinition
    state: AgentSourceState
    tool?: SourceToolStatus
    enablingTool: boolean
    onEnableTool: (tool: SourceToolStatus) => void
    onToggleEntity: (entityId: string) => void
    onConfigureFilters?: () => void
}

function Expansion({
    agent,
    state,
    tool,
    enablingTool,
    onEnableTool,
    onToggleEntity,
    onConfigureFilters,
}: ExpansionProps): JSX.Element {
    const [filter, setFilter] = useState('')
    const { entities } = state
    const noun = agent.entityNoun ?? 'items'
    const query = filter.trim().toLowerCase()
    const visible = query ? entities.filter((entity) => entity.name.toLowerCase().includes(query)) : entities
    const enabledCount = entities.filter((entity) => entity.enabled).length
    const toolOff = !!tool && !tool.enabled

    return (
        <div className="flex flex-col gap-2 border-t border-primary bg-surface-secondary px-3 py-2.5">
            <p className="mb-0 text-xs text-secondary">
                {agent.description}{' '}
                {agent.docsUrl && (
                    <Link to={agent.docsUrl} target="_blank" className="whitespace-nowrap text-xs">
                        Learn about {agent.docsLabel ?? agent.label}
                        <IconArrowUpRight />
                    </Link>
                )}
            </p>

            {toolOff && tool && (
                <div className="flex items-center gap-2">
                    <span className="text-xs text-warning">
                        {tool.toolName} is off, so this source has nothing to read.
                    </span>
                    {tool.enablement && (
                        <LemonButton
                            type="secondary"
                            size="xsmall"
                            loading={enablingTool}
                            onClick={() => onEnableTool(tool)}
                        >
                            Turn it on
                        </LemonButton>
                    )}
                </div>
            )}

            {onConfigureFilters && (
                <div className="flex items-center gap-2">
                    <span className="text-xs text-secondary">Limit which recordings this source analyzes.</span>
                    <LemonButton type="secondary" size="xsmall" onClick={onConfigureFilters}>
                        Configure filters
                    </LemonButton>
                </div>
            )}

            {state.entitiesLoading ? (
                <LemonSkeleton className="h-16 w-full" />
            ) : entities.length > 0 ? (
                <div className="flex flex-col gap-1.5">
                    <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-default">
                            {enabledCount} of {entities.length} {noun} on
                        </span>
                        {entities.length > ENTITY_FILTER_THRESHOLD && (
                            <LemonInput
                                type="search"
                                size="xsmall"
                                className="w-52"
                                placeholder={`Filter ${noun}`}
                                value={filter}
                                onChange={setFilter}
                            />
                        )}
                        <div className="flex-1" />
                        {agent.manageUrl && (
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                to={agent.manageUrl}
                                icon={<IconPlus />}
                                targetBlank
                            >
                                New {agent.entityNounSingular}
                            </LemonButton>
                        )}
                    </div>
                    <div className="max-h-46 overflow-y-auto rounded border border-primary bg-surface-primary">
                        {visible.length === 0 ? (
                            <p className="mb-0 px-2 py-3 text-center text-xs text-muted">
                                No {noun} match that filter.
                            </p>
                        ) : (
                            visible.map((entity) => (
                                <EntityRow
                                    key={entity.id}
                                    entity={entity}
                                    onToggle={() => onToggleEntity(entity.id)}
                                    disabledReason={
                                        state.loading
                                            ? 'Saving'
                                            : toolOff && !entity.enabled
                                              ? `Turn on ${tool?.toolName} first. This source reads its data.`
                                              : undefined
                                    }
                                />
                            ))
                        )}
                    </div>
                </div>
            ) : agent.entityNoun ? (
                <div className="flex items-center gap-2">
                    <span className="text-xs text-secondary">No {noun} yet.</span>
                    {agent.manageUrl && (
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            to={agent.manageUrl}
                            icon={<IconPlus />}
                            targetBlank
                        >
                            New {agent.entityNounSingular}
                        </LemonButton>
                    )}
                </div>
            ) : null}
        </div>
    )
}

interface AgentRowProps {
    agent: AgentRosterDefinition
    state: AgentSourceState
    tool?: SourceToolStatus
    expanded: boolean
    enablingTool: boolean
    onExpand: () => void
    onToggle: (source: AgentRosterSource) => void
    onToggleEntity: (source: AgentRosterSource, entityId: string) => void
    onEnableTool: (tool: SourceToolStatus) => void
    onConfigureFilters?: () => void
}

const AgentRow = memo(function AgentRow({
    agent,
    state,
    tool,
    expanded,
    enablingTool,
    onExpand,
    onToggle,
    onToggleEntity,
    onEnableTool,
    onConfigureFilters,
}: AgentRowProps): JSX.Element {
    const { armed, loading, requiresSetup, syncStatus, entities } = state
    const status = resolveAgentStatus(armed, syncStatus)
    const toolOff = !!tool && !tool.enabled
    // An off tool blocks arming (the source would watch nothing), never disarming.
    const armingBlocked = toolOff && !armed
    const tag = notableTag(status, armed, toolOff, tool)
    const enabledCount = entities.filter((entity) => entity.enabled).length
    const partiallyOn = enabledCount > 0 && enabledCount < entities.length
    const switchState: boolean | 'indeterminate' = entities.length && partiallyOn ? 'indeterminate' : armed

    return (
        <div>
            <div
                onClick={onExpand}
                className={`group flex h-13 cursor-pointer items-center gap-2 px-2 transition-colors ${
                    expanded ? 'bg-surface-secondary' : 'hover:bg-surface-secondary'
                }`}
            >
                <StatusDot status={status} tool={tool} toolOff={toolOff} />
                <AgentIcon source={agent} />
                <div className="flex min-w-0 flex-1 flex-col">
                    <div className="flex items-center gap-2">
                        <span
                            className={`truncate text-sm leading-5 ${armed ? 'font-medium text-default' : 'text-secondary'}`}
                        >
                            {agent.label}
                        </span>
                        {agent.alpha && (
                            <LemonTag type="completion" size="small">
                                Alpha
                            </LemonTag>
                        )}
                        {agent.legacy && (
                            <LemonTag type="caution" size="small">
                                Legacy
                            </LemonTag>
                        )}
                    </div>
                    <span className="truncate text-xs leading-4 text-muted">{agent.watches ?? agent.description}</span>
                </div>
                {tag && (
                    <LemonTag type={tag.type} size="small">
                        {tag.label}
                    </LemonTag>
                )}
                <span className="w-38 shrink-0 truncate text-right text-xs text-muted">
                    {entities.length > 0 && `${enabledCount} of ${entities.length} ${agent.entityNoun} on`}
                </span>
                {/* eslint-disable-next-line react/no-unknown-property */}
                <div className="flex w-13 shrink-0 justify-end" onClick={(e) => e.stopPropagation()}>
                    {loading ? (
                        <Spinner className="text-base" />
                    ) : requiresSetup ? (
                        <LemonButton type="secondary" size="xsmall" onClick={() => onToggle(agent.source)}>
                            Connect
                        </LemonButton>
                    ) : (
                        <LemonSwitch
                            size="xsmall"
                            checked={switchState}
                            onChange={() => onToggle(agent.source)}
                            disabledReason={
                                armingBlocked
                                    ? `Turn on ${tool?.toolName} first. This source reads its data.`
                                    : undefined
                            }
                            aria-label={`Arm ${agent.label}`}
                        />
                    )}
                </div>
                <IconChevronRight
                    className={`shrink-0 text-muted transition-transform ${expanded ? 'rotate-90' : ''}`}
                />
            </div>
            {expanded && (
                <Expansion
                    agent={agent}
                    state={state}
                    tool={tool}
                    enablingTool={enablingTool}
                    onEnableTool={onEnableTool}
                    onToggleEntity={(entityId) => onToggleEntity(agent.source, entityId)}
                    onConfigureFilters={onConfigureFilters}
                />
            )}
        </div>
    )
})

export function AgentsRoster(): JSX.Element {
    const {
        sessionAnalysisConfig,
        conversationsConfig,
        evalReportsConfig,
        anomalyInvestigationConfig,
        githubIssuesConfig,
        linearIssuesConfig,
        zendeskTicketsConfig,
        pgAnalyzeIssuesConfig,
        healthChecksConfig,
        ciSignalsConfig,
        ciSignalsConfigLoading,
        ciSignalsIsFullyEnabled,
        errorTrackingIsFullyEnabled,
        errorTrackingTypeStates,
        visionScanners,
        visionScannersLoading,
        evaluations,
        evaluationsLoading,
        signalEmittingEvaluationIds,
        isSessionAnalysisToggling,
        isConversationsToggling,
        isEvalReportsToggling,
        isAnomalyInvestigationToggling,
        isErrorTrackingToggling,
        isGithubIssuesToggling,
        isLinearIssuesToggling,
        isZendeskTicketsToggling,
        isPgAnalyzeIssuesToggling,
        isHealthChecksToggling,
        isCiSignalsToggling,
        toolStatusBySource,
        enablingTool,
    } = useValues(signalSourcesLogic)
    const {
        toggleSessionAnalysis,
        toggleConversations,
        toggleErrorTracking,
        toggleErrorTrackingType,
        toggleEvalReports,
        toggleEvaluationSignals,
        toggleCiSignals,
        toggleAnomalyInvestigation,
        toggleHealthChecks,
        toggleScannerSignals,
        initiateDataWarehouseSourceToggle,
        enableSourceTool,
        openSessionAnalysisSetup,
    } = useActions(signalSourcesLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const [expandedSource, setExpandedSource] = useState<AgentRosterSource | null>(null)

    const scannerEntities = useMemo(
        (): RosterEntity[] =>
            (visionScanners ?? []).map((scanner) => ({
                id: scanner.id,
                name: scanner.name,
                detail: scanner.description || undefined,
                kind: scanner.scanner_type,
                enabled: scanner.emits_signals ?? false,
            })),
        [visionScanners]
    )

    const evaluationEntities = useMemo(
        (): RosterEntity[] =>
            (evaluations ?? []).map((evaluation) => ({
                id: evaluation.id,
                name: evaluation.name,
                detail: evaluation.description || undefined,
                kind: evaluation.evaluation_type,
                enabled: signalEmittingEvaluationIds.includes(evaluation.id),
            })),
        [evaluations, signalEmittingEvaluationIds]
    )

    const errorTrackingEntities = useMemo(
        (): RosterEntity[] =>
            errorTrackingTypeStates.map(({ sourceType, enabled }) => ({
                id: sourceType,
                name: ERROR_TRACKING_TYPE_LABELS[sourceType]?.name ?? sourceType,
                detail: ERROR_TRACKING_TYPE_LABELS[sourceType]?.detail,
                enabled,
            })),
        [errorTrackingTypeStates]
    )

    const stateFor = useCallback(
        (source: AgentRosterSource): AgentSourceState => {
            const base = { entities: [] as RosterEntity[], entitiesLoading: false }
            const dwState = (config: SignalSourceConfig | null, loading: boolean): AgentSourceState => ({
                ...base,
                armed: !!config?.enabled,
                loading,
                // No config row yet → the source has never been connected; surface a Connect button.
                requiresSetup: config === null,
                syncStatus: config?.status,
            })
            switch (source) {
                case 'error_tracking':
                    return {
                        ...base,
                        armed: errorTrackingIsFullyEnabled,
                        loading: isErrorTrackingToggling,
                        requiresSetup: false,
                        syncStatus: null,
                        entities: errorTrackingEntities,
                    }
                case 'conversations':
                    return {
                        ...base,
                        armed: !!conversationsConfig?.enabled,
                        loading: isConversationsToggling,
                        requiresSetup: false,
                        syncStatus: conversationsConfig?.status,
                    }
                case 'replay_vision':
                    return {
                        ...base,
                        armed: scannerEntities.some((entity) => entity.enabled),
                        loading: visionScannersLoading,
                        requiresSetup: false,
                        syncStatus: null,
                        entities: scannerEntities,
                        entitiesLoading: visionScanners === null && visionScannersLoading,
                    }
                case 'session_replay':
                    return {
                        ...base,
                        armed: !!sessionAnalysisConfig?.enabled,
                        loading: isSessionAnalysisToggling,
                        requiresSetup: false,
                        syncStatus: sessionAnalysisConfig?.status,
                    }
                case 'llm_analytics':
                    return {
                        ...base,
                        armed: !!evalReportsConfig?.enabled,
                        loading: isEvalReportsToggling,
                        requiresSetup: false,
                        syncStatus: null,
                        entities: evaluationEntities,
                        entitiesLoading: evaluations === null && evaluationsLoading,
                    }
                case 'analytics':
                    return {
                        ...base,
                        armed: !!anomalyInvestigationConfig?.enabled,
                        loading: isAnomalyInvestigationToggling,
                        requiresSetup: false,
                        syncStatus: anomalyInvestigationConfig?.status,
                    }
                case 'health_checks':
                    return {
                        ...base,
                        armed: !!healthChecksConfig?.enabled,
                        loading: isHealthChecksToggling,
                        requiresSetup: false,
                        syncStatus: healthChecksConfig?.status,
                    }
                case 'github':
                    return dwState(githubIssuesConfig, isGithubIssuesToggling)
                case 'linear':
                    return dwState(linearIssuesConfig, isLinearIssuesToggling)
                case 'zendesk':
                    return dwState(zendeskTicketsConfig, isZendeskTicketsToggling)
                case 'pganalyze':
                    return dwState(pgAnalyzeIssuesConfig, isPgAnalyzeIssuesToggling)
                case 'engineering_analytics':
                    return {
                        ...base,
                        armed: ciSignalsIsFullyEnabled,
                        // Config load counts as loading: rendering Connect before it resolves misleads.
                        loading: isCiSignalsToggling || ciSignalsConfigLoading,
                        requiresSetup: !(ciSignalsConfig?.configured ?? false),
                        syncStatus: ciSignalsConfig?.sync_status,
                    }
            }
        },
        [
            errorTrackingIsFullyEnabled,
            errorTrackingEntities,
            isErrorTrackingToggling,
            conversationsConfig,
            isConversationsToggling,
            scannerEntities,
            visionScanners,
            visionScannersLoading,
            sessionAnalysisConfig,
            isSessionAnalysisToggling,
            evalReportsConfig,
            evaluationEntities,
            evaluations,
            evaluationsLoading,
            isEvalReportsToggling,
            anomalyInvestigationConfig,
            isAnomalyInvestigationToggling,
            healthChecksConfig,
            isHealthChecksToggling,
            githubIssuesConfig,
            isGithubIssuesToggling,
            linearIssuesConfig,
            isLinearIssuesToggling,
            zendeskTicketsConfig,
            isZendeskTicketsToggling,
            pgAnalyzeIssuesConfig,
            isPgAnalyzeIssuesToggling,
            ciSignalsConfig,
            ciSignalsConfigLoading,
            ciSignalsIsFullyEnabled,
            isCiSignalsToggling,
        ]
    )

    const handleToggle = useCallback(
        (source: AgentRosterSource) => {
            switch (source) {
                case 'replay_vision': {
                    // Replay Vision has no row of its own, so the master switch is the scanners:
                    // arm them all when none emits, and stand them all down otherwise.
                    const next = !scannerEntities.some((entity) => entity.enabled)
                    scannerEntities
                        .filter((entity) => entity.enabled !== next)
                        .forEach((entity) => toggleScannerSignals(entity.id))
                    return
                }
                case 'error_tracking':
                    toggleErrorTracking()
                    return
                case 'conversations':
                    toggleConversations()
                    return
                case 'session_replay':
                    toggleSessionAnalysis()
                    return
                case 'llm_analytics':
                    toggleEvalReports()
                    return
                case 'analytics':
                    toggleAnomalyInvestigation()
                    return
                case 'health_checks':
                    toggleHealthChecks()
                    return
                case 'github':
                case 'linear':
                case 'zendesk':
                case 'pganalyze':
                    initiateDataWarehouseSourceToggle(source)
                    return
                case 'engineering_analytics':
                    toggleCiSignals()
                    return
            }
        },
        [
            scannerEntities,
            toggleScannerSignals,
            toggleErrorTracking,
            toggleConversations,
            toggleSessionAnalysis,
            toggleEvalReports,
            toggleCiSignals,
            toggleAnomalyInvestigation,
            toggleHealthChecks,
            initiateDataWarehouseSourceToggle,
        ]
    )

    const handleToggleEntity = useCallback(
        (source: AgentRosterSource, entityId: string) => {
            if (source === 'replay_vision') {
                toggleScannerSignals(entityId)
            } else if (source === 'llm_analytics') {
                toggleEvaluationSignals(entityId)
            } else if (source === 'error_tracking') {
                toggleErrorTrackingType(entityId as SignalSourceType)
            }
        },
        [toggleScannerSignals, toggleEvaluationSignals, toggleErrorTrackingType]
    )

    const visibleGroups = AGENT_ROSTER_GROUPS.map((group) => ({
        ...group,
        agents: group.agents.filter((agent) => !agent.flag || featureFlags[agent.flag]),
    }))
    const allAgents = visibleGroups.flatMap((group) => group.agents)
    const armedCount = allAgents.filter((agent) => stateFor(agent.source).armed).length

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center gap-1.5 text-xs text-muted">
                <span className={`size-2 rounded-full ${armedCount ? 'bg-success' : 'bg-border-bold'}`} />
                <span>
                    {armedCount} of {allAgents.length} sources on. Open a source to see what it watches.
                </span>
            </div>

            {visibleGroups.map((group) => (
                <div key={group.label} className="flex flex-col gap-1">
                    <span className="text-xs font-medium text-muted">{group.label}</span>
                    <div className="divide-y divide-primary overflow-hidden rounded border border-primary">
                        {group.agents.map((agent) => (
                            <AgentRow
                                key={agent.source}
                                agent={agent}
                                state={stateFor(agent.source)}
                                tool={toolStatusBySource[agent.source]}
                                expanded={expandedSource === agent.source}
                                enablingTool={
                                    !!enablingTool && enablingTool === toolStatusBySource[agent.source]?.enablement
                                }
                                onExpand={() =>
                                    setExpandedSource((current) => (current === agent.source ? null : agent.source))
                                }
                                onToggle={handleToggle}
                                onToggleEntity={handleToggleEntity}
                                onEnableTool={(tool) => tool.enablement && enableSourceTool(tool.enablement)}
                                onConfigureFilters={
                                    agent.source === 'session_replay' ? openSessionAnalysisSetup : undefined
                                }
                            />
                        ))}
                    </div>
                </div>
            ))}
        </div>
    )
}

function AgentRowSkeleton(): JSX.Element {
    return (
        <div className="flex h-13 items-center gap-2 px-2">
            <LemonSkeleton className="size-2 shrink-0 rounded-full" />
            <LemonSkeleton className="size-4 shrink-0 rounded" />
            <div className="flex min-w-0 flex-1 flex-col gap-1">
                <LemonSkeleton className="h-3 w-32" />
                <LemonSkeleton className="h-2.5 w-56" />
            </div>
            <LemonSkeleton className="h-4 w-8 shrink-0 rounded-full" />
        </div>
    )
}

export function AgentsRosterSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <LemonSkeleton className="h-3 w-48" />
            {AGENT_ROSTER_GROUPS.map((group) => (
                <div key={group.label} className="flex flex-col gap-1">
                    <LemonSkeleton className="h-3 w-24" />
                    <div className="divide-y divide-primary overflow-hidden rounded border border-primary">
                        {group.agents.map((agent) => (
                            <AgentRowSkeleton key={agent.source} />
                        ))}
                    </div>
                </div>
            ))}
        </div>
    )
}

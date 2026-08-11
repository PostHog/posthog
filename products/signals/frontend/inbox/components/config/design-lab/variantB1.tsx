import { useMemo, useState } from 'react'

import { IconArrowUpRight, IconChevronRight, IconPlus } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonSelect,
    LemonSwitch,
    LemonTag,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { LemonTagType } from 'lib/lemon-ui/LemonTag/LemonTag'

import { getSourceProductMeta } from '../../badges/sourceProductIcons'
import {
    LAB_GROUPS,
    LabEntity,
    LabSetting,
    LabSource,
    LabSourceKey,
    LabStatus,
    VariantProps,
    isEntityDriven,
} from './contract'

/**
 * THROWAWAY design lab variant.
 *
 * B1: B's control board, one density step softer. Every row carries a second line saying what the
 * source watches, the count reads as a sentence, and a chevron says the row opens. This is the
 * design that won, and the one the shipped `AgentsRoster` came from.
 */

export const WIDTH_B1 = 760

/** The source we point a brand new project at, since it needs no setup and fires on day one. */
const FIRST_STEP_KEY = 'error_tracking'

/** Above this, an expanded entity list gets a filter box instead of just a scroll bar. */
const FILTER_THRESHOLD = 8

/**
 * The at-rest gloss, short enough to survive one truncated line. Only sources whose description is
 * too long to read at a glance need an entry; the rest fall back to the description itself.
 */
const GLOSS: Partial<Record<LabSourceKey, string>> = {
    error_tracking: 'New errors, regressions, and spikes in your app',
    replay_vision: 'UX problems your scanners find while watching recordings',
    llm_analytics: 'AI quality problems your evaluations catch',
    session_replay: 'UX problems in recordings, now covered by replay vision',
    analytics: 'Unexpected shifts in your product metrics',
    health_checks: 'Missing events, proxy gaps, and outdated SDKs',
    pganalyze: 'Slow Postgres queries and bad indexes',
}

function glossFor(source: LabSource): string {
    return GLOSS[source.key] ?? source.description.replace(/\.$/, '')
}

interface BoardRow {
    source: LabSource
    entities: LabEntity[]
    armed: boolean
    status: LabStatus
    toolEnabled: boolean
    enabledCount: number
}

interface Overrides {
    sources: Record<string, boolean>
    entities: Record<string, boolean>
    tools: Record<string, boolean>
}

const EMPTY_OVERRIDES: Overrides = { sources: {}, entities: {}, tools: {} }

function statusFor(source: LabSource, armed: boolean): LabStatus {
    if (source.status === 'sync_failed') {
        return 'sync_failed'
    }
    if (!armed) {
        return 'standby'
    }
    return source.status === 'standby' ? 'watching' : source.status
}

function buildRows(sources: LabSource[], overrides: Overrides): BoardRow[] {
    return sources.map((source) => {
        const entities = (source.entities ?? []).map((entity) => ({
            ...entity,
            enabled: overrides.entities[`${source.key}:${entity.id}`] ?? entity.enabled,
        }))
        const enabledCount = entities.filter((entity) => entity.enabled).length
        const armed = isEntityDriven(source) ? enabledCount > 0 : (overrides.sources[source.key] ?? source.armed)
        return {
            source,
            entities,
            armed,
            status: statusFor(source, armed),
            toolEnabled: overrides.tools[source.key] ?? source.tool?.enabled ?? true,
            enabledCount,
        }
    })
}

function StatusDot({ row }: { row: BoardRow }): JSX.Element {
    const { status, source, toolEnabled } = row
    const receiving = source.tool?.receivingData ?? null
    const hasTool = !!source.tool
    const toolOff = hasTool && !toolEnabled

    let className = 'bg-border-bold'
    let title = 'Standby'
    if (toolOff) {
        title = `${source.tool?.name} is off, so this source has nothing to read`
    } else if (status === 'sync_failed') {
        className = 'bg-danger'
        title = 'Sync failed'
    } else if (status === 'syncing') {
        className = 'bg-accent animate-pulse'
        title = 'Syncing'
    } else if (status === 'watching') {
        // A hollow dot means watching but nothing has arrived yet, so the two read apart at a glance.
        className = receiving === false ? 'border border-success' : 'bg-success'
        title = receiving === false ? 'Watching, no data yet' : receiving ? 'Watching, receiving data' : 'Watching'
    }

    return (
        <Tooltip title={title}>
            <span className={`size-2 shrink-0 rounded-full ${className}`} />
        </Tooltip>
    )
}

function notableTag(row: BoardRow): { label: string; type: LemonTagType } | null {
    if (row.source.tool && !row.toolEnabled) {
        return { label: 'Tool off', type: 'warning' }
    }
    if (row.status === 'sync_failed') {
        return { label: 'Sync failed', type: 'danger' }
    }
    if (row.status === 'syncing') {
        return { label: 'Syncing', type: 'primary' }
    }
    if (row.armed && row.source.tool?.receivingData === false) {
        return { label: 'No data yet', type: 'muted' }
    }
    return null
}

function SourceIcon({ source }: { source: LabSource }): JSX.Element | null {
    const meta = getSourceProductMeta(source.product)
    if (!meta) {
        return null
    }
    const Icon = meta.Icon
    return <Icon className={`shrink-0 text-base ${meta.colorClass}`} />
}

function SettingControl({ setting }: { setting: LabSetting }): JSX.Element {
    if (setting.control === 'switch') {
        return <LemonSwitch size="xsmall" checked={!!setting.value} onChange={() => {}} />
    }
    if (setting.control === 'select') {
        return <LemonSelect size="xsmall" value={String(setting.value)} options={setting.options ?? []} />
    }
    return (
        <LemonInput
            type="number"
            size="xsmall"
            className="w-24"
            defaultValue={Number(setting.value)}
            suffix={setting.suffix ? <span className="text-muted">{setting.suffix}</span> : undefined}
        />
    )
}

interface EntityRowProps {
    entity: LabEntity
    onToggle: () => void
}

function EntityRow({ entity, onToggle }: EntityRowProps): JSX.Element {
    return (
        <button
            type="button"
            onClick={onToggle}
            className="flex w-full items-center gap-2 px-2 py-1 text-left hover:bg-surface-secondary"
        >
            <LemonSwitch size="xxsmall" checked={entity.enabled} onChange={onToggle} />
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
            {entity.systemNote && (
                <Tooltip title={entity.systemNote}>
                    <LemonTag size="small" type="caution">
                        Turned off automatically
                    </LemonTag>
                </Tooltip>
            )}
        </button>
    )
}

interface ExpansionProps {
    row: BoardRow
    filter: string
    onFilterChange: (value: string) => void
    onToggleEntity: (entityId: string) => void
    onToggleAll: (entityIds: string[], next: boolean) => void
    onEnableTool: () => void
}

function Expansion({
    row,
    filter,
    onFilterChange,
    onToggleEntity,
    onToggleAll,
    onEnableTool,
}: ExpansionProps): JSX.Element {
    const { source, entities, toolEnabled } = row
    const query = filter.trim().toLowerCase()
    const visible = query ? entities.filter((entity) => entity.name.toLowerCase().includes(query)) : entities
    const allVisibleOn = visible.length > 0 && visible.every((entity) => entity.enabled)

    return (
        <div className="flex flex-col gap-2 border-t border-primary bg-surface-secondary px-3 py-2.5">
            <p className="mb-0 text-xs text-secondary">
                {source.description}{' '}
                {source.docsUrl && (
                    <Link to={source.docsUrl} target="_blank" className="whitespace-nowrap text-xs">
                        Learn about {source.docsLabel ?? source.label}
                        <IconArrowUpRight />
                    </Link>
                )}
            </p>

            {source.tool && !toolEnabled && (
                <div className="flex items-center gap-2">
                    <span className="text-xs text-warning">
                        {source.tool.name} is off, so this source has nothing to read.
                    </span>
                    <LemonButton type="secondary" size="xsmall" onClick={onEnableTool}>
                        Turn it on
                    </LemonButton>
                </div>
            )}

            {source.settings?.length ? (
                <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
                    {source.settings.map((setting) => (
                        <div key={setting.key} className="flex items-center gap-2">
                            {setting.help ? (
                                <Tooltip title={setting.help}>
                                    <span className="text-xs text-secondary">{setting.label}</span>
                                </Tooltip>
                            ) : (
                                <span className="text-xs text-secondary">{setting.label}</span>
                            )}
                            <SettingControl setting={setting} />
                        </div>
                    ))}
                </div>
            ) : null}

            {entities.length > 0 && (
                <div className="flex flex-col gap-1.5">
                    <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-default">
                            {row.enabledCount} of {entities.length} {source.entityNoun} on
                        </span>
                        {entities.length > FILTER_THRESHOLD && (
                            <LemonInput
                                type="search"
                                size="xsmall"
                                className="w-52"
                                placeholder={`Filter ${source.entityNoun}`}
                                value={filter}
                                onChange={onFilterChange}
                            />
                        )}
                        <div className="flex-1" />
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            onClick={() =>
                                onToggleAll(
                                    visible.map((entity) => entity.id),
                                    !allVisibleOn
                                )
                            }
                            disabledReason={visible.length === 0 ? 'Nothing matches the filter' : undefined}
                        >
                            {allVisibleOn ? 'Turn all off' : 'Turn all on'}
                        </LemonButton>
                        {source.entityManageUrl && (
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                to={source.entityManageUrl}
                                icon={<IconPlus />}
                                targetBlank
                            >
                                New {source.entityNounSingular}
                            </LemonButton>
                        )}
                    </div>
                    <div className="max-h-46 overflow-y-auto rounded border border-primary bg-surface-primary">
                        {visible.length === 0 ? (
                            <p className="mb-0 px-2 py-3 text-center text-xs text-muted">
                                No {source.entityNoun} match that filter.
                            </p>
                        ) : (
                            visible.map((entity) => (
                                <EntityRow key={entity.id} entity={entity} onToggle={() => onToggleEntity(entity.id)} />
                            ))
                        )}
                    </div>
                </div>
            )}

            {entities.length === 0 && source.requiresSetup && (
                <div className="flex items-center gap-2">
                    <span className="text-xs text-secondary">Connect {source.label} to start reading from it.</span>
                    <LemonButton type="primary" size="xsmall">
                        Connect
                    </LemonButton>
                </div>
            )}
        </div>
    )
}

interface SourceLineProps {
    row: BoardRow
    expanded: boolean
    firstStep: boolean
    onExpand: () => void
    onToggleSource: () => void
}

function SourceLine({ row, expanded, firstStep, onExpand, onToggleSource }: SourceLineProps): JSX.Element {
    const { source, entities, armed, toolEnabled, enabledCount } = row
    const tag = notableTag(row)
    const entityDriven = isEntityDriven(source)
    const armingBlocked = !!source.tool && !toolEnabled && !armed
    const switchState: boolean | 'indeterminate' =
        entityDriven && enabledCount > 0 && enabledCount < entities.length ? 'indeterminate' : armed

    return (
        <div
            onClick={onExpand}
            className={`group flex h-13 cursor-pointer items-center gap-2 px-2 transition-colors ${
                expanded ? 'bg-surface-secondary' : 'hover:bg-surface-secondary'
            }`}
        >
            <StatusDot row={row} />
            <SourceIcon source={source} />
            <div className="flex min-w-0 flex-1 flex-col">
                <div className="flex items-center gap-2">
                    <span
                        className={`truncate text-sm leading-5 ${armed ? 'font-medium text-default' : 'text-secondary'}`}
                    >
                        {source.label}
                    </span>
                    {source.alpha && (
                        <LemonTag type="completion" size="small">
                            Alpha
                        </LemonTag>
                    )}
                    {source.legacy && (
                        <LemonTag type="caution" size="small">
                            Legacy
                        </LemonTag>
                    )}
                    {firstStep && (
                        <LemonTag type="highlight" size="small">
                            Start here
                        </LemonTag>
                    )}
                </div>
                <span className="truncate text-xs leading-4 text-muted">{glossFor(source)}</span>
            </div>
            {tag && (
                <LemonTag type={tag.type} size="small">
                    {tag.label}
                </LemonTag>
            )}
            <span className="w-38 shrink-0 truncate text-right text-xs text-muted">
                {entities.length > 0 && (
                    <>
                        {enabledCount} of {entities.length} {source.entityNoun} on
                    </>
                )}
            </span>
            {/* eslint-disable-next-line react/no-unknown-property */}
            <div className="flex w-13 shrink-0 justify-end" onClick={(e) => e.stopPropagation()}>
                {source.requiresSetup ? (
                    <LemonButton type="secondary" size="xsmall">
                        Connect
                    </LemonButton>
                ) : (
                    <LemonSwitch
                        size="xsmall"
                        checked={switchState}
                        onChange={onToggleSource}
                        disabledReason={
                            armingBlocked
                                ? `Turn on ${source.tool?.name} first. This source reads its data.`
                                : undefined
                        }
                        aria-label={`Turn on ${source.label}`}
                    />
                )}
            </div>
            <IconChevronRight
                className={`shrink-0 text-muted transition-transform ${
                    expanded ? 'rotate-90' : 'group-hover:translate-x-0.5'
                }`}
            />
        </div>
    )
}

export function VariantB1({ sources }: VariantProps): JSX.Element {
    const [overrides, setOverrides] = useState<Overrides>(EMPTY_OVERRIDES)
    const [expandedKey, setExpandedKey] = useState<string | null>(null)
    const [filter, setFilter] = useState('')

    const rows = useMemo(() => buildRows(sources, overrides), [sources, overrides])
    const armedCount = rows.filter((row) => row.armed).length
    const firstStepKey = armedCount === 0 ? FIRST_STEP_KEY : null

    const expand = (key: string): void => {
        setExpandedKey((current) => (current === key ? null : key))
        setFilter('')
    }

    const toggleSource = (row: BoardRow): void => {
        if (isEntityDriven(row.source)) {
            const next = row.enabledCount === 0
            setOverrides((current) => ({
                ...current,
                entities: {
                    ...current.entities,
                    ...Object.fromEntries(row.entities.map((entity) => [`${row.source.key}:${entity.id}`, next])),
                },
            }))
            return
        }
        setOverrides((current) => ({
            ...current,
            sources: { ...current.sources, [row.source.key]: !row.armed },
        }))
    }

    const toggleEntity = (sourceKey: string, entityId: string, next: boolean): void => {
        setOverrides((current) => ({
            ...current,
            entities: { ...current.entities, [`${sourceKey}:${entityId}`]: next },
        }))
    }

    const toggleAll = (sourceKey: string, entityIds: string[], next: boolean): void => {
        setOverrides((current) => ({
            ...current,
            entities: {
                ...current.entities,
                ...Object.fromEntries(entityIds.map((id) => [`${sourceKey}:${id}`, next])),
            },
        }))
    }

    const enableTool = (sourceKey: string): void => {
        setOverrides((current) => ({ ...current, tools: { ...current.tools, [sourceKey]: true } }))
    }

    const startFirstSource = (): void => {
        setOverrides((current) => ({ ...current, sources: { ...current.sources, [FIRST_STEP_KEY]: true } }))
        setExpandedKey(FIRST_STEP_KEY)
        setFilter('')
    }

    return (
        <div className="flex flex-col gap-3">
            {armedCount === 0 ? (
                <LemonBanner
                    type="info"
                    action={{ children: 'Turn on error tracking', onClick: startFirstSource }}
                    className="text-sm"
                >
                    Nothing is watching yet. Turn on a source and its findings start landing in your inbox.
                </LemonBanner>
            ) : (
                <div className="flex items-center gap-1.5 text-xs text-muted">
                    <span className="size-2 rounded-full bg-success" />
                    <span>
                        {armedCount} of {rows.length} sources on. Open a source to see what it watches.
                    </span>
                </div>
            )}

            {LAB_GROUPS.map((group) => (
                <div key={group} className="flex flex-col gap-1">
                    <span className="text-xs font-medium text-muted">{group}</span>
                    <div className="divide-y divide-primary overflow-hidden rounded border border-primary">
                        {rows
                            .filter((row) => row.source.group === group)
                            .map((row) => {
                                const expanded = expandedKey === row.source.key
                                return (
                                    <div key={row.source.key}>
                                        <SourceLine
                                            row={row}
                                            expanded={expanded}
                                            firstStep={firstStepKey === row.source.key}
                                            onExpand={() => expand(row.source.key)}
                                            onToggleSource={() => toggleSource(row)}
                                        />
                                        {expanded && (
                                            <Expansion
                                                row={row}
                                                filter={filter}
                                                onFilterChange={setFilter}
                                                onToggleEntity={(entityId) => {
                                                    const entity = row.entities.find((e) => e.id === entityId)
                                                    toggleEntity(row.source.key, entityId, !entity?.enabled)
                                                }}
                                                onToggleAll={(entityIds, next) =>
                                                    toggleAll(row.source.key, entityIds, next)
                                                }
                                                onEnableTool={() => enableTool(row.source.key)}
                                            />
                                        )}
                                    </div>
                                )
                            })}
                    </div>
                </div>
            ))}
        </div>
    )
}

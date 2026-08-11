import { useState } from 'react'

import { IconArrowUpRight, IconPlus } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonSelect,
    LemonSwitch,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { LemonTagType } from 'lib/lemon-ui/LemonTag/LemonTag'

import { getSourceProductMeta } from '../../badges/sourceProductIcons'
import {
    LAB_GROUPS,
    LabScenario,
    LabSetting,
    LabSource,
    LabSourceKey,
    LabStatus,
    VariantProps,
    isEntityDriven,
} from './contract'

/**
 * B3: the dense control board as a real table, where labelled columns explain the values.
 *
 * THROWAWAY design lab variant. Local state only, so every control in the grid actually moves.
 */

export const WIDTH_B3 = 760

/** Above this many children the list gets a filter box rather than only a scroll bar. */
const ENTITY_FILTER_THRESHOLD = 8

/**
 * Column widths are shared by both tables so the columns line up across the gap between them.
 * Each cell caps its content just inside its column, so auto table layout cannot widen a column
 * in one table and knock the two out of alignment.
 */
const COLUMN_WIDTHS = { source: 248, watches: 168, feeding: 176, on: 56 }

/** Roughly 24 characters, so the cell never wraps at this column width. */
const GLOSSES: Record<LabSourceKey, string> = {
    error_tracking: 'new and spiking issues',
    replay_vision: 'UX problems in replays',
    llm_analytics: 'failing evaluations',
    session_replay: 'the older replay check',
    conversations: 'problems in support',
    analytics: 'shifts in your metrics',
    health_checks: 'missing events, old SDKs',
    github: 'issues in your repos',
    linear: 'issues your team tracks',
    zendesk: 'incoming tickets',
    pganalyze: 'slow queries and indexes',
}

interface BoardState {
    armed: Record<string, boolean>
    tools: Record<string, boolean>
    entities: Record<string, boolean>
    connected: Record<string, boolean>
    settings: Record<string, string | number | boolean>
}

interface Board {
    isArmed: (source: LabSource) => boolean
    isConnected: (source: LabSource) => boolean
    isToolOn: (source: LabSource) => boolean
    isEntityOn: (source: LabSource, entityId: string) => boolean
    enabledCount: (source: LabSource) => number
    settingValue: (source: LabSource, setting: LabSetting) => string | number | boolean
    toggleSource: (source: LabSource) => void
    toggleEntity: (source: LabSource, entityId: string) => void
    turnOnTool: (source: LabSource) => void
    setSetting: (source: LabSource, setting: LabSetting, value: string | number | boolean) => void
    arm: (key: LabSourceKey) => void
}

function entityKey(source: LabSource, entityId: string): string {
    return `${source.key}:${entityId}`
}

function initialBoard(sources: LabSource[]): BoardState {
    const state: BoardState = { armed: {}, tools: {}, entities: {}, connected: {}, settings: {} }
    for (const source of sources) {
        state.armed[source.key] = source.armed
        state.connected[source.key] = !source.requiresSetup
        if (source.tool) {
            state.tools[source.key] = source.tool.enabled
        }
        for (const entity of source.entities ?? []) {
            state.entities[entityKey(source, entity.id)] = entity.enabled
        }
        for (const setting of source.settings ?? []) {
            state.settings[`${source.key}:${setting.key}`] = setting.value
        }
    }
    return state
}

function useBoard(sources: LabSource[]): Board {
    const [state, setState] = useState<BoardState>(() => initialBoard(sources))

    const enabledCount = (source: LabSource): number =>
        (source.entities ?? []).filter((entity) => state.entities[entityKey(source, entity.id)]).length

    const isArmed = (source: LabSource): boolean =>
        isEntityDriven(source) ? enabledCount(source) > 0 : !!state.armed[source.key]

    const setAllEntities = (source: LabSource, enabled: boolean): void =>
        setState((current) => {
            const entities = { ...current.entities }
            for (const entity of source.entities ?? []) {
                entities[entityKey(source, entity.id)] = enabled
            }
            return { ...current, entities }
        })

    return {
        isArmed,
        enabledCount,
        isConnected: (source) => !!state.connected[source.key],
        isToolOn: (source) => !source.tool || !!state.tools[source.key],
        isEntityOn: (source, entityId) => !!state.entities[entityKey(source, entityId)],
        settingValue: (source, setting) => state.settings[`${source.key}:${setting.key}`] ?? setting.value,
        toggleSource: (source) => {
            if (source.requiresSetup && !state.connected[source.key]) {
                setState((current) => ({
                    ...current,
                    connected: { ...current.connected, [source.key]: true },
                    armed: { ...current.armed, [source.key]: true },
                }))
                return
            }
            if (isEntityDriven(source)) {
                setAllEntities(source, !isArmed(source))
                return
            }
            setState((current) => ({
                ...current,
                armed: { ...current.armed, [source.key]: !current.armed[source.key] },
            }))
        },
        toggleEntity: (source, entityId) =>
            setState((current) => ({
                ...current,
                entities: {
                    ...current.entities,
                    [entityKey(source, entityId)]: !current.entities[entityKey(source, entityId)],
                },
            })),
        turnOnTool: (source) =>
            setState((current) => ({ ...current, tools: { ...current.tools, [source.key]: true } })),
        setSetting: (source, setting, value) =>
            setState((current) => ({
                ...current,
                settings: { ...current.settings, [`${source.key}:${setting.key}`]: value },
            })),
        arm: (key) => setState((current) => ({ ...current, armed: { ...current.armed, [key]: true } })),
    }
}

function statusOf(source: LabSource, armed: boolean): LabStatus {
    if (source.status === 'sync_failed') {
        return 'sync_failed'
    }
    if (!armed) {
        return 'standby'
    }
    return source.status === 'syncing' ? 'syncing' : 'watching'
}

function SourceIcon({ source }: { source: LabSource }): JSX.Element | null {
    const meta = getSourceProductMeta(source.product)
    if (!meta) {
        return null
    }
    const Icon = meta.Icon
    return <Icon className={`shrink-0 text-base ${meta.colorClass}`} />
}

function StatusDot({
    source,
    status,
    toolOff,
}: {
    source: LabSource
    status: LabStatus
    toolOff: boolean
}): JSX.Element {
    let className = 'bg-border-bold'
    let title = 'Standby'
    if (toolOff) {
        title = `${source.tool?.name} is off, so this source has nothing to read`
    } else if (status === 'sync_failed') {
        className = 'bg-danger'
        title = 'Sync failed'
    } else if (status === 'syncing') {
        className = 'bg-accent'
        title = 'Syncing'
    } else if (status === 'watching') {
        // A hollow dot means watching but nothing has arrived, so the two read apart at a glance.
        className = source.tool?.receivingData === false ? 'border border-success' : 'bg-success'
        title = source.tool?.receivingData === false ? 'Watching, no data yet' : 'Watching'
    }
    return (
        <Tooltip title={title}>
            <span className={`size-2 shrink-0 rounded-full ${className}`} />
        </Tooltip>
    )
}

/** Only the states worth interrupting a scan for. Everything healthy shows no tag at all. */
function notableTag(
    source: LabSource,
    status: LabStatus,
    armed: boolean,
    toolOff: boolean
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
    if (armed && source.tool?.receivingData === false) {
        return { label: 'No data yet', type: 'muted' }
    }
    return null
}

/** Terse, because the column header already says these numbers are what reaches the inbox. */
function countPhrase(source: LabSource, board: Board): string {
    const total = source.entities?.length ?? 0
    const noun = source.entityNoun ?? 'items'
    if (total > 0) {
        const enabled = board.enabledCount(source)
        if (enabled === 0) {
            return `no ${noun}`
        }
        if (enabled === total) {
            return `all ${total} ${noun}`
        }
        return `${enabled} of ${total} ${noun}`
    }
    if (source.requiresSetup && !board.isConnected(source)) {
        return 'not connected'
    }
    return board.isArmed(source) ? 'everything it finds' : 'nothing'
}

function SettingRow({ source, setting, board }: { source: LabSource; setting: LabSetting; board: Board }): JSX.Element {
    const value = board.settingValue(source, setting)
    return (
        <div className="flex items-center gap-2">
            {setting.control === 'switch' ? (
                <LemonSwitch
                    size="xsmall"
                    checked={!!value}
                    onChange={(next) => board.setSetting(source, setting, next)}
                    aria-label={setting.label}
                />
            ) : setting.control === 'select' ? (
                <LemonSelect
                    size="xsmall"
                    value={String(value)}
                    options={setting.options ?? []}
                    onChange={(next) => board.setSetting(source, setting, next ?? '')}
                />
            ) : (
                <LemonInput
                    type="number"
                    size="xsmall"
                    className="w-24"
                    value={Number(value)}
                    suffix={setting.suffix ? <span>{setting.suffix}</span> : undefined}
                    onChange={(next) => board.setSetting(source, setting, next ?? 0)}
                />
            )}
            <span className="shrink-0 text-xs text-default">{setting.label}</span>
            {setting.help && <span className="min-w-0 flex-1 truncate text-xs text-muted">{setting.help}</span>}
        </div>
    )
}

function Expansion({
    source,
    board,
    scenario,
}: {
    source: LabSource
    board: Board
    scenario: LabScenario
}): JSX.Element {
    const [filter, setFilter] = useState('')
    const entities = source.entities ?? []
    const noun = source.entityNoun ?? 'items'
    const query = filter.trim().toLowerCase()
    const visible = query ? entities.filter((entity) => entity.name.toLowerCase().includes(query)) : entities
    const toolOff = !board.isToolOn(source)
    // The heavy case keeps a fixed well, so opening a source never moves the board's height.
    const fixedWell = scenario === 'heavy' || entities.length > ENTITY_FILTER_THRESHOLD

    return (
        <div className="flex flex-col gap-2 py-1">
            <p className="mb-0 text-xs text-secondary">
                {source.description}{' '}
                {source.docsUrl && (
                    <Link to={source.docsUrl} target="_blank" className="whitespace-nowrap text-xs">
                        Learn about {source.docsLabel ?? source.label}
                        <IconArrowUpRight />
                    </Link>
                )}
            </p>

            {toolOff && source.tool && (
                <div className="flex items-center gap-2">
                    <span className="text-xs text-warning">
                        {source.tool.name} is off, so this source has nothing to read.
                    </span>
                    <LemonButton type="secondary" size="xsmall" onClick={() => board.turnOnTool(source)}>
                        Turn it on
                    </LemonButton>
                </div>
            )}

            {(source.settings ?? []).map((setting) => (
                <SettingRow key={setting.key} source={source} setting={setting} board={board} />
            ))}

            {entities.length > 0 && (
                <div className="flex flex-col gap-1.5">
                    <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-default">
                            {board.enabledCount(source)} of {entities.length} {noun} on
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
                    <div
                        className={`${
                            fixedWell ? 'h-46' : 'max-h-46'
                        } overflow-y-auto rounded border border-primary bg-surface-primary`}
                    >
                        {visible.length === 0 ? (
                            <p className="mb-0 px-2 py-3 text-center text-xs text-muted">
                                No {noun} match that filter.
                            </p>
                        ) : (
                            visible.map((entity) => {
                                const on = board.isEntityOn(source, entity.id)
                                return (
                                    <div
                                        key={entity.id}
                                        className="flex items-center gap-2 px-2 py-1 hover:bg-surface-secondary"
                                    >
                                        <LemonSwitch
                                            size="xxsmall"
                                            checked={on}
                                            onChange={() => board.toggleEntity(source, entity.id)}
                                            disabledReason={
                                                toolOff && !on
                                                    ? `Turn on ${source.tool?.name} first. This source reads its data.`
                                                    : undefined
                                            }
                                            aria-label={entity.name}
                                        />
                                        <span
                                            className={`max-w-60 shrink-0 truncate text-xs font-medium ${
                                                on ? 'text-default' : 'text-muted'
                                            }`}
                                        >
                                            {entity.name}
                                        </span>
                                        {entity.kind && (
                                            <LemonTag size="small" type="muted">
                                                {entity.kind}
                                            </LemonTag>
                                        )}
                                        <span
                                            className={`min-w-0 flex-1 truncate text-xs ${
                                                entity.systemNote ? 'text-warning' : 'text-muted'
                                            }`}
                                        >
                                            {entity.systemNote ?? entity.detail}
                                        </span>
                                    </div>
                                )
                            })
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}

function GroupTable({
    heading,
    sources,
    board,
    scenario,
    expanded,
    onExpandedChange,
}: {
    heading: string
    sources: LabSource[]
    board: Board
    scenario: LabScenario
    expanded: LabSourceKey | null
    onExpandedChange: (key: LabSourceKey | null) => void
}): JSX.Element {
    const columns: LemonTableColumns<LabSource> = [
        {
            title: heading,
            key: 'source',
            width: COLUMN_WIDTHS.source,
            render: function RenderSource(_, source) {
                const armed = board.isArmed(source)
                const toolOff = !board.isToolOn(source)
                return (
                    <div className="flex max-w-58 items-center gap-2">
                        <StatusDot source={source} status={statusOf(source, armed)} toolOff={toolOff} />
                        <SourceIcon source={source} />
                        <span className={`truncate text-sm ${armed ? 'font-medium text-default' : 'text-secondary'}`}>
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
                    </div>
                )
            },
        },
        {
            title: 'What it watches',
            key: 'watches',
            width: COLUMN_WIDTHS.watches,
            render: function RenderWatches(_, source) {
                return <div className="max-w-38 truncate text-xs text-muted">{GLOSSES[source.key]}</div>
            },
        },
        {
            title: 'Feeding your inbox',
            key: 'feeding',
            width: COLUMN_WIDTHS.feeding,
            render: function RenderFeeding(_, source) {
                const armed = board.isArmed(source)
                const toolOff = !board.isToolOn(source)
                const tag = notableTag(source, statusOf(source, armed), armed, toolOff)
                return (
                    <div className="flex max-w-40 items-center gap-1.5">
                        <span className="truncate text-xs text-muted">{countPhrase(source, board)}</span>
                        {tag && (
                            <LemonTag type={tag.type} size="small">
                                {tag.label}
                            </LemonTag>
                        )}
                    </div>
                )
            },
        },
        {
            title: 'On',
            key: 'on',
            width: COLUMN_WIDTHS.on,
            render: function RenderOn(_, source) {
                const armed = board.isArmed(source)
                const toolOff = !board.isToolOn(source)
                const total = source.entities?.length ?? 0
                const enabled = board.enabledCount(source)
                const switchState: boolean | 'indeterminate' =
                    isEntityDriven(source) && enabled > 0 && enabled < total ? 'indeterminate' : armed
                return (
                    // The control must not open the row it sits in.
                    /* eslint-disable-next-line react/no-unknown-property */
                    <div className="flex justify-end" onClick={(event) => event.stopPropagation()}>
                        {source.requiresSetup && !board.isConnected(source) ? (
                            <LemonButton type="secondary" size="xsmall" onClick={() => board.toggleSource(source)}>
                                Connect
                            </LemonButton>
                        ) : (
                            <LemonSwitch
                                size="xsmall"
                                checked={switchState}
                                onChange={() => board.toggleSource(source)}
                                disabledReason={
                                    toolOff && !armed
                                        ? `Turn on ${source.tool?.name} first. This source reads its data.`
                                        : undefined
                                }
                                aria-label={`Turn on ${source.label}`}
                            />
                        )}
                    </div>
                )
            },
        },
    ]

    return (
        <LemonTable
            columns={columns}
            dataSource={sources}
            rowKey="key"
            size="small"
            uppercaseHeader={false}
            useURLForSorting={false}
            expandable={{
                noIndent: true,
                expandedRowRender: (source) => <Expansion source={source} board={board} scenario={scenario} />,
                isRowExpanded: (source) => expanded === source.key,
                onRowExpand: (source) => onExpandedChange(source.key),
                onRowCollapse: () => onExpandedChange(null),
            }}
            onRow={(source) => ({
                onClick: () => onExpandedChange(expanded === source.key ? null : source.key),
            })}
        />
    )
}

export function VariantB3({ sources, scenario }: VariantProps): JSX.Element {
    const board = useBoard(sources)
    const [expanded, setExpanded] = useState<LabSourceKey | null>(null)
    const armedCount = sources.filter((source) => board.isArmed(source)).length

    return (
        <div className="flex flex-col gap-3">
            {armedCount === 0 ? (
                <LemonBanner
                    type="info"
                    action={{
                        children: 'Turn on error tracking',
                        onClick: () => {
                            board.arm('error_tracking')
                            setExpanded('error_tracking')
                        },
                    }}
                >
                    <span className="text-sm">
                        Nothing is watching yet, so your inbox stays empty. Turn on a source to start.
                    </span>
                </LemonBanner>
            ) : (
                <div className="flex items-center gap-1.5 text-xs text-muted">
                    <span className="size-2 rounded-full bg-success" />
                    <span>
                        {armedCount} of {sources.length} sources on
                    </span>
                </div>
            )}

            {LAB_GROUPS.map((group) => (
                <GroupTable
                    key={group}
                    heading={group === 'PostHog data' ? 'PostHog data sources' : 'External sources'}
                    sources={sources.filter((source) => source.group === group)}
                    board={board}
                    scenario={scenario}
                    expanded={expanded}
                    onExpandedChange={setExpanded}
                />
            ))}
        </div>
    )
}

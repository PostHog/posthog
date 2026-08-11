import clsx from 'clsx'
import { useState } from 'react'

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
import { isEntityDriven, LAB_GROUPS, LabEntity, LabSetting, LabSource, VariantProps } from './contract'

/**
 * Variant B: dense control board.
 *
 * The bet is subtraction. Once you know what these sources are, the catalog copy is noise, so every
 * source gets one compact line and the copy only comes back when you open the line.
 */
export const WIDTH_B = 760

/** Past this many children the list needs a filter, not only a scroll bar. */
const FILTER_AFTER = 8
/** The source the board opens on when nothing is watching yet. */
const FIRST_ACTION_KEY = 'error_tracking'

function StatusDot({
    source,
    armed,
    toolEnabled,
}: {
    source: LabSource
    armed: boolean
    toolEnabled: boolean
}): JSX.Element {
    const receiving = source.tool?.receivingData
    let className = 'bg-border-bold'
    let title = 'Standby'
    if (source.tool && !toolEnabled) {
        title = `${source.tool.name} is off, so this source has nothing to read`
    } else if (source.status === 'sync_failed') {
        className = 'bg-danger'
        title = 'Sync failed'
    } else if (armed && source.status === 'syncing') {
        className = 'bg-accent'
        title = 'Syncing'
    } else if (armed) {
        // Solid means data is arriving, a hollow ring means watching with nothing arrived yet.
        className = receiving ? 'bg-success' : 'border border-success'
        title = receiving ? 'Watching, receiving data' : 'Watching, no data yet'
    }
    return (
        <Tooltip title={title}>
            <span className={`size-2 shrink-0 rounded-full ${className}`} />
        </Tooltip>
    )
}

/** Only the states worth interrupting a scan for. Everything healthy carries no tag at all. */
function notableTag(
    source: LabSource,
    armed: boolean,
    toolEnabled: boolean
): { label: string; type: LemonTagType } | null {
    if (source.tool && !toolEnabled) {
        return { label: 'Tool off', type: 'warning' }
    }
    if (source.status === 'sync_failed') {
        return { label: 'Sync failed', type: 'danger' }
    }
    if (armed && source.status === 'syncing') {
        return { label: 'Syncing', type: 'primary' }
    }
    if (armed && source.tool?.receivingData === false) {
        return { label: 'No data yet', type: 'muted' }
    }
    if (source.alpha) {
        return { label: 'Alpha', type: 'completion' }
    }
    if (source.legacy) {
        return { label: 'Legacy', type: 'caution' }
    }
    return null
}

function SettingControl({
    setting,
    value,
    onChange,
}: {
    setting: LabSetting
    value: string | number | boolean
    onChange: (next: string | number | boolean) => void
}): JSX.Element {
    if (setting.control === 'switch') {
        return <LemonSwitch size="xsmall" checked={!!value} onChange={onChange} aria-label={setting.label} />
    }
    if (setting.control === 'select') {
        return (
            <LemonSelect
                size="xsmall"
                value={String(value)}
                options={setting.options ?? []}
                onChange={(next) => onChange(next ?? '')}
            />
        )
    }
    return (
        <LemonInput
            type="number"
            size="xsmall"
            className="w-24"
            value={Number(value)}
            suffix={setting.suffix ? <span>{setting.suffix}</span> : undefined}
            onChange={(next) => onChange(next ?? 0)}
        />
    )
}

function EntityRow({
    entity,
    checked,
    onToggle,
    disabledReason,
}: {
    entity: LabEntity
    checked: boolean
    onToggle: () => void
    disabledReason?: string
}): JSX.Element {
    return (
        <div className="flex items-center gap-2 px-2 py-1 hover:bg-surface-secondary">
            <LemonSwitch
                size="xxsmall"
                checked={checked}
                onChange={onToggle}
                disabledReason={disabledReason}
                aria-label={entity.name}
            />
            <span
                className={`max-w-60 shrink-0 truncate text-xs font-medium ${checked ? 'text-default' : 'text-muted'}`}
            >
                {entity.name}
            </span>
            {entity.kind && (
                <LemonTag size="small" type="muted">
                    {entity.kind}
                </LemonTag>
            )}
            <span className="min-w-0 flex-1 truncate text-xs text-muted">{entity.systemNote ?? entity.detail}</span>
        </div>
    )
}

function Expansion({
    source,
    toolEnabled,
    entityOn,
    settingValue,
    onToggleEntity,
    onSetEntities,
    onEnableTool,
    onChangeSetting,
}: {
    source: LabSource
    toolEnabled: boolean
    entityOn: (entityId: string) => boolean
    settingValue: (setting: LabSetting) => string | number | boolean
    onToggleEntity: (entityId: string) => void
    onSetEntities: (entityIds: string[], next: boolean) => void
    onEnableTool: () => void
    onChangeSetting: (setting: LabSetting, next: string | number | boolean) => void
}): JSX.Element {
    const [filter, setFilter] = useState('')
    const entities = source.entities ?? []
    const noun = source.entityNoun ?? 'items'
    const settings = source.settings ?? []
    const query = filter.trim().toLowerCase()
    const visible = query ? entities.filter((entity) => entity.name.toLowerCase().includes(query)) : entities
    const onCount = entities.filter((entity) => entityOn(entity.id)).length
    const toolOff = !!source.tool && !toolEnabled
    const filteredAllOn = visible.length > 0 && visible.every((entity) => entityOn(entity.id))
    // A filter turns the bulk button into a scalpel, so it acts on what is on screen, not everything.
    const bulkLabel = filteredAllOn ? `Turn ${query ? 'these' : 'all'} off` : `Turn ${query ? 'these' : 'all'} on`

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

            {toolOff && (
                <div className="flex items-center gap-2">
                    <span className="text-xs text-warning">
                        {source.tool?.name} is off, so this source has nothing to read.
                    </span>
                    <LemonButton type="secondary" size="xsmall" onClick={onEnableTool}>
                        Turn it on
                    </LemonButton>
                </div>
            )}

            {settings.map((setting) => (
                <div key={setting.key} className="flex items-center gap-3">
                    <div className="flex min-w-0 flex-1 flex-col">
                        <span className="text-xs font-medium text-default">{setting.label}</span>
                        {setting.help && <span className="text-xs text-muted">{setting.help}</span>}
                    </div>
                    <SettingControl
                        setting={setting}
                        value={settingValue(setting)}
                        onChange={(next) => onChangeSetting(setting, next)}
                    />
                </div>
            ))}

            {entities.length > 0 && (
                <div className="flex flex-col gap-1.5">
                    <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-default">
                            {onCount} of {entities.length} {noun} on
                        </span>
                        {entities.length > FILTER_AFTER && (
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
                        {entities.length > FILTER_AFTER && (
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                onClick={() =>
                                    onSetEntities(
                                        visible.map((entity) => entity.id),
                                        !filteredAllOn
                                    )
                                }
                            >
                                {bulkLabel}
                            </LemonButton>
                        )}
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
                    {/* Fixed height past the filter threshold, so filtering never moves the board. */}
                    <div
                        className={clsx(
                            'overflow-y-auto overscroll-contain rounded border border-primary bg-surface-primary',
                            entities.length > FILTER_AFTER ? 'h-46' : 'max-h-46'
                        )}
                    >
                        {visible.length === 0 ? (
                            <p className="mb-0 px-2 py-3 text-center text-xs text-muted">
                                No {noun} match that filter.
                            </p>
                        ) : (
                            visible.map((entity) => (
                                <EntityRow
                                    key={entity.id}
                                    entity={entity}
                                    checked={entityOn(entity.id)}
                                    onToggle={() => onToggleEntity(entity.id)}
                                    disabledReason={
                                        toolOff && !entityOn(entity.id)
                                            ? `Turn on ${source.tool?.name} first. This source reads its data.`
                                            : undefined
                                    }
                                />
                            ))
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}

interface LineProps {
    source: LabSource
    armed: boolean
    expanded: boolean
    connected: boolean
    toolEnabled: boolean
    entityOn: (entityId: string) => boolean
    settingValue: (setting: LabSetting) => string | number | boolean
    onExpand: () => void
    onToggleArmed: () => void
    onConnect: () => void
    onToggleEntity: (entityId: string) => void
    onSetEntities: (entityIds: string[], next: boolean) => void
    onEnableTool: () => void
    onChangeSetting: (setting: LabSetting, next: string | number | boolean) => void
}

function SourceLine({
    source,
    armed,
    expanded,
    connected,
    toolEnabled,
    entityOn,
    settingValue,
    onExpand,
    onToggleArmed,
    onConnect,
    onToggleEntity,
    onSetEntities,
    onEnableTool,
    onChangeSetting,
}: LineProps): JSX.Element {
    const entities = source.entities ?? []
    const onCount = entities.filter((entity) => entityOn(entity.id)).length
    const meta = getSourceProductMeta(source.product)
    const Icon = meta?.Icon
    const tag = notableTag(source, armed, toolEnabled)
    const toolOff = !!source.tool && !toolEnabled
    const needsSetup = !!source.requiresSetup && !connected
    const masterChecked: boolean | 'indeterminate' =
        isEntityDriven(source) && onCount > 0 && onCount < entities.length ? 'indeterminate' : armed

    return (
        <div>
            <div
                onClick={onExpand}
                className={clsx(
                    'flex h-9 cursor-pointer items-center gap-2 px-2 transition-colors',
                    expanded ? 'bg-surface-secondary' : 'hover:bg-surface-secondary'
                )}
            >
                <StatusDot source={source} armed={armed} toolEnabled={toolEnabled} />
                {Icon ? <Icon className={`shrink-0 text-base ${meta?.colorClass ?? ''}`} /> : null}
                <span className={`truncate text-sm ${armed ? 'font-medium text-default' : 'text-secondary'}`}>
                    {source.label}
                </span>
                {tag && (
                    <LemonTag type={tag.type} size="small">
                        {tag.label}
                    </LemonTag>
                )}
                <div className="flex-1" />
                <span className="w-12 shrink-0 text-right text-xs tabular-nums text-muted">
                    {entities.length > 0 && (
                        <Tooltip title={`${onCount} of ${entities.length} ${source.entityNoun} on`}>
                            <span>
                                {onCount}/{entities.length}
                            </span>
                        </Tooltip>
                    )}
                </span>
                {/* eslint-disable-next-line react/no-unknown-property */}
                <div className="flex w-14 shrink-0 justify-end" onClick={(event) => event.stopPropagation()}>
                    {needsSetup ? (
                        <LemonButton type="secondary" size="xsmall" onClick={onConnect}>
                            Connect
                        </LemonButton>
                    ) : (
                        <LemonSwitch
                            size="xsmall"
                            checked={masterChecked}
                            onChange={onToggleArmed}
                            disabledReason={
                                toolOff && !armed
                                    ? `Turn on ${source.tool?.name} first. This source reads its data.`
                                    : undefined
                            }
                            aria-label={`Turn on ${source.label}`}
                        />
                    )}
                </div>
                <IconChevronRight
                    className={`shrink-0 text-muted transition-transform ${expanded ? 'rotate-90' : ''}`}
                />
            </div>
            {expanded && (
                <Expansion
                    source={source}
                    toolEnabled={toolEnabled}
                    entityOn={entityOn}
                    settingValue={settingValue}
                    onToggleEntity={onToggleEntity}
                    onSetEntities={onSetEntities}
                    onEnableTool={onEnableTool}
                    onChangeSetting={onChangeSetting}
                />
            )}
        </div>
    )
}

export function VariantB({ sources, scenario }: VariantProps): JSX.Element {
    const [armedByKey, setArmedByKey] = useState<Record<string, boolean>>(() =>
        Object.fromEntries(sources.map((source) => [source.key, source.armed]))
    )
    const [entityByKey, setEntityByKey] = useState<Record<string, boolean>>(() =>
        Object.fromEntries(
            sources.flatMap((source) =>
                (source.entities ?? []).map((entity) => [`${source.key}:${entity.id}`, entity.enabled])
            )
        )
    )
    const [toolByKey, setToolByKey] = useState<Record<string, boolean>>(() =>
        Object.fromEntries(sources.map((source) => [source.key, source.tool?.enabled ?? true]))
    )
    const [settingByKey, setSettingByKey] = useState<Record<string, string | number | boolean>>(() =>
        Object.fromEntries(
            sources.flatMap((source) =>
                (source.settings ?? []).map((setting) => [`${source.key}:${setting.key}`, setting.value])
            )
        )
    )
    const [connectedKeys, setConnectedKeys] = useState<string[]>([])
    const [expandedKey, setExpandedKey] = useState<string | null>(null)

    const setEntities = (source: LabSource, entityIds: string[], next: boolean): void =>
        setEntityByKey((current) => ({
            ...current,
            ...Object.fromEntries(entityIds.map((entityId) => [`${source.key}:${entityId}`, next])),
        }))

    const isArmed = (source: LabSource): boolean =>
        isEntityDriven(source)
            ? (source.entities ?? []).some((entity) => entityByKey[`${source.key}:${entity.id}`])
            : !!armedByKey[source.key]

    const toggleArmed = (source: LabSource): void => {
        const next = !isArmed(source)
        if (isEntityDriven(source)) {
            setEntities(
                source,
                (source.entities ?? []).map((entity) => entity.id),
                next
            )
            return
        }
        setArmedByKey((current) => ({ ...current, [source.key]: next }))
    }

    const armedCount = sources.filter(isArmed).length
    const firstAction = sources.find((source) => source.key === FIRST_ACTION_KEY)

    return (
        <div className="flex flex-col gap-3">
            {armedCount === 0 && firstAction ? (
                <LemonBanner
                    type="info"
                    action={{
                        children: `Turn on ${firstAction.label.toLowerCase()}`,
                        onClick: () => {
                            setArmedByKey((current) => ({ ...current, [firstAction.key]: true }))
                            setEntities(
                                firstAction,
                                (firstAction.entities ?? []).map((entity) => entity.id),
                                true
                            )
                            setExpandedKey(firstAction.key)
                        },
                    }}
                >
                    {scenario === 'nothingOn'
                        ? 'Nothing is watching yet, so your inbox stays empty.'
                        : 'Every source is off, so your inbox stays empty.'}
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
                <div key={group} className="flex flex-col gap-1">
                    <span className="text-xs font-medium text-muted">{group}</span>
                    <div className="divide-y divide-primary overflow-hidden rounded border border-primary">
                        {sources
                            .filter((source) => source.group === group)
                            .map((source) => (
                                <SourceLine
                                    key={source.key}
                                    source={source}
                                    armed={isArmed(source)}
                                    expanded={expandedKey === source.key}
                                    connected={connectedKeys.includes(source.key)}
                                    toolEnabled={toolByKey[source.key] ?? true}
                                    entityOn={(entityId) => !!entityByKey[`${source.key}:${entityId}`]}
                                    settingValue={(setting) => settingByKey[`${source.key}:${setting.key}`]}
                                    onExpand={() =>
                                        setExpandedKey((current) => (current === source.key ? null : source.key))
                                    }
                                    onToggleArmed={() => toggleArmed(source)}
                                    onConnect={() => {
                                        setConnectedKeys((current) => [...current, source.key])
                                        setArmedByKey((current) => ({ ...current, [source.key]: true }))
                                    }}
                                    onToggleEntity={(entityId) =>
                                        setEntityByKey((current) => ({
                                            ...current,
                                            [`${source.key}:${entityId}`]: !current[`${source.key}:${entityId}`],
                                        }))
                                    }
                                    onSetEntities={(entityIds, next) => setEntities(source, entityIds, next)}
                                    onEnableTool={() => setToolByKey((current) => ({ ...current, [source.key]: true }))}
                                    onChangeSetting={(setting, next) =>
                                        setSettingByKey((current) => ({
                                            ...current,
                                            [`${source.key}:${setting.key}`]: next,
                                        }))
                                    }
                                />
                            ))}
                    </div>
                </div>
            ))}
        </div>
    )
}

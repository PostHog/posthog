import clsx from 'clsx'
import { useState } from 'react'

import { IconArrowUpRight, IconGear, IconPlus } from '@posthog/icons'
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
 * Variant A: Scout-style rows.
 *
 * The bet: this panel is a sibling of the Scout troop panel, so it should read like one. Full-width
 * cards, one per source, each keeping its catalog copy, with a gear that opens the settings inline.
 */
export const WIDTH_A = 760

/** Past this many children the list scrolls inside the row rather than growing the modal. */
const SCROLL_AFTER = 6
/** Past this many children scrolling alone is not enough to find one, so the list gains a filter. */
const FILTER_AFTER = 8

type RowStatus = 'standby' | 'watching' | 'syncing' | 'sync_failed' | 'tool_off' | 'no_data'

const STATUS_TAGS: Record<RowStatus, { label: string; type: LemonTagType }> = {
    tool_off: { label: 'Tool off', type: 'warning' },
    sync_failed: { label: 'Sync failed', type: 'danger' },
    syncing: { label: 'Syncing', type: 'primary' },
    watching: { label: 'Watching', type: 'success' },
    no_data: { label: 'No data yet', type: 'muted' },
    standby: { label: 'Standby', type: 'muted' },
}

function rowStatus(source: LabSource, armed: boolean, toolEnabled: boolean): RowStatus {
    if (source.tool && !toolEnabled) {
        return 'tool_off'
    }
    if (source.status === 'sync_failed') {
        return 'sync_failed'
    }
    if (!armed) {
        return 'standby'
    }
    if (source.status === 'syncing') {
        return 'syncing'
    }
    if (source.tool?.receivingData === false) {
        return 'no_data'
    }
    return 'watching'
}

function SourceIcon({ source }: { source: LabSource }): JSX.Element {
    const meta = getSourceProductMeta(source.product)
    const Icon = meta?.Icon
    return (
        <div className="flex size-8 shrink-0 items-center justify-center rounded border border-primary bg-surface-primary">
            {Icon ? <Icon className={`text-base ${meta?.colorClass ?? ''}`} /> : null}
        </div>
    )
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

function SettingsBlock({
    settings,
    valueOf,
    onChange,
}: {
    settings: LabSetting[]
    valueOf: (setting: LabSetting) => string | number | boolean
    onChange: (setting: LabSetting, next: string | number | boolean) => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            {settings.map((setting) => (
                <div key={setting.key} className="flex items-center gap-3">
                    <div className="flex min-w-0 flex-1 flex-col">
                        <span className="text-xs font-medium text-default">{setting.label}</span>
                        {setting.help && <span className="text-xs text-muted">{setting.help}</span>}
                    </div>
                    <SettingControl
                        setting={setting}
                        value={valueOf(setting)}
                        onChange={(next) => onChange(setting, next)}
                    />
                </div>
            ))}
        </div>
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
        <div className="flex items-start gap-2 px-2 py-1.5 hover:bg-surface-secondary">
            <LemonSwitch
                size="xxsmall"
                className="mt-0.5"
                checked={checked}
                onChange={onToggle}
                disabledReason={disabledReason}
                aria-label={entity.name}
            />
            <div className="flex min-w-0 flex-1 flex-col">
                <div className="flex items-center gap-2">
                    <span className={`truncate text-xs font-medium ${checked ? 'text-default' : 'text-muted'}`}>
                        {entity.name}
                    </span>
                    {entity.kind && (
                        <LemonTag size="small" type="muted">
                            {entity.kind}
                        </LemonTag>
                    )}
                </div>
                {entity.detail && <span className="truncate text-xs text-muted">{entity.detail}</span>}
                {entity.systemNote && <span className="text-xs text-warning">{entity.systemNote}</span>}
            </div>
        </div>
    )
}

function EntityList({
    source,
    isOn,
    onToggle,
    disabledReason,
}: {
    source: LabSource
    isOn: (entityId: string) => boolean
    onToggle: (entityId: string) => void
    disabledReason: (entity: LabEntity) => string | undefined
}): JSX.Element {
    const [filter, setFilter] = useState('')
    const entities = source.entities ?? []
    const noun = source.entityNoun ?? 'items'
    const query = filter.trim().toLowerCase()
    const visible = query ? entities.filter((entity) => entity.name.toLowerCase().includes(query)) : entities
    const onCount = entities.filter((entity) => isOn(entity.id)).length

    return (
        <div className="flex flex-col gap-1.5">
            <div className="flex flex-wrap items-center gap-2">
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
            {entities.length > FILTER_AFTER && (
                <span className="text-xs text-muted">
                    Showing {visible.length} of {entities.length} {noun}
                </span>
            )}
            <div
                className={clsx(
                    'divide-y divide-primary rounded border border-primary bg-surface-primary',
                    entities.length > SCROLL_AFTER && 'max-h-72 overflow-y-auto overscroll-contain'
                )}
            >
                {visible.length === 0 ? (
                    <p className="mb-0 px-2 py-3 text-center text-xs text-muted">No {noun} match that filter.</p>
                ) : (
                    visible.map((entity) => (
                        <EntityRow
                            key={entity.id}
                            entity={entity}
                            checked={isOn(entity.id)}
                            onToggle={() => onToggle(entity.id)}
                            disabledReason={disabledReason(entity)}
                        />
                    ))
                )}
            </div>
        </div>
    )
}

interface RowProps {
    source: LabSource
    armed: boolean
    dimmed: boolean
    connected: boolean
    toolEnabled: boolean
    entityOn: (entityId: string) => boolean
    settingValue: (setting: LabSetting) => string | number | boolean
    onToggleArmed: () => void
    onConnect: () => void
    onToggleEntity: (entityId: string) => void
    onEnableTool: () => void
    onChangeSetting: (setting: LabSetting, next: string | number | boolean) => void
}

function SourceRow({
    source,
    armed,
    dimmed,
    connected,
    toolEnabled,
    entityOn,
    settingValue,
    onToggleArmed,
    onConnect,
    onToggleEntity,
    onEnableTool,
    onChangeSetting,
}: RowProps): JSX.Element {
    const [settingsOpen, setSettingsOpen] = useState(false)
    const entities = source.entities ?? []
    const onCount = entities.filter((entity) => entityOn(entity.id)).length
    const entityDriven = isEntityDriven(source)
    const status = rowStatus(source, armed, toolEnabled)
    const tag = STATUS_TAGS[status]
    const toolOff = !!source.tool && !toolEnabled
    const needsSetup = !!source.requiresSetup && !connected
    const hasBody = entities.length > 0 || (source.settings ?? []).length > 0 || toolOff

    return (
        <div
            className={clsx(
                'flex flex-col rounded border border-primary bg-bg-light px-4 py-3 transition-colors',
                dimmed && 'opacity-65'
            )}
        >
            <div className="flex items-start gap-3">
                <SourceIcon source={source} />
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="truncate text-sm font-medium text-default">{source.label}</span>
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
                        <LemonTag type={tag.type} size="small">
                            {tag.label}
                        </LemonTag>
                    </div>
                    <p className="mb-0 text-xs text-secondary">
                        {source.description}{' '}
                        {source.docsUrl && (
                            <Link to={source.docsUrl} target="_blank" className="whitespace-nowrap text-xs">
                                Learn about {source.docsLabel ?? source.label}
                                <IconArrowUpRight />
                            </Link>
                        )}
                    </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                    {needsSetup ? (
                        <LemonButton type="secondary" size="small" onClick={onConnect}>
                            Connect
                        </LemonButton>
                    ) : entityDriven ? null : (
                        <LemonSwitch
                            size="small"
                            checked={armed}
                            onChange={onToggleArmed}
                            disabledReason={
                                toolOff && !armed
                                    ? `Turn on ${source.tool?.name} first. This source reads its data.`
                                    : undefined
                            }
                            aria-label={`Turn on ${source.label}`}
                        />
                    )}
                    {hasBody && (
                        <Tooltip title={`${source.label} settings`}>
                            <LemonButton
                                size="small"
                                icon={<IconGear />}
                                active={settingsOpen}
                                onClick={() => setSettingsOpen((open) => !open)}
                                aria-label={`${source.label} settings`}
                            >
                                {entityDriven
                                    ? entities.length > 0
                                        ? `${onCount} of ${entities.length} ${source.entityNoun} watching`
                                        : `No ${source.entityNoun} yet`
                                    : undefined}
                            </LemonButton>
                        </Tooltip>
                    )}
                </div>
            </div>

            {settingsOpen && hasBody && (
                <div className="mt-3 flex flex-col gap-3 border-t border-primary pt-3">
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
                    {(source.settings ?? []).length > 0 && (
                        <SettingsBlock
                            settings={source.settings ?? []}
                            valueOf={settingValue}
                            onChange={onChangeSetting}
                        />
                    )}
                    {entities.length > 0 && (
                        <EntityList
                            source={source}
                            isOn={entityOn}
                            onToggle={onToggleEntity}
                            disabledReason={(entity) =>
                                toolOff && !entityOn(entity.id)
                                    ? `Turn on ${source.tool?.name} first. This source reads its data.`
                                    : undefined
                            }
                        />
                    )}
                </div>
            )}
        </div>
    )
}

export function VariantA({ sources, scenario }: VariantProps): JSX.Element {
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

    const isArmed = (source: LabSource): boolean =>
        isEntityDriven(source)
            ? (source.entities ?? []).some((entity) => entityByKey[`${source.key}:${entity.id}`])
            : !!armedByKey[source.key]

    const armedCount = sources.filter(isArmed).length

    return (
        <div className="flex flex-col gap-4">
            {armedCount === 0 ? (
                <LemonBanner type="info">
                    {scenario === 'nothingOn'
                        ? 'Nothing is watching yet. Turn on a source and its agent starts looking into what it finds.'
                        : 'Every source is off, so nothing reaches your inbox. Turn one back on to start again.'}
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
                <div key={group} className="flex flex-col gap-2">
                    <span className="text-xs font-medium text-muted">{group}</span>
                    {sources
                        .filter((source) => source.group === group)
                        .map((source) => (
                            <SourceRow
                                key={source.key}
                                source={source}
                                armed={isArmed(source)}
                                // Dimming every row at once reads as broken, so it only kicks in
                                // once something else is on to contrast with.
                                dimmed={!isArmed(source) && armedCount > 0}
                                connected={connectedKeys.includes(source.key)}
                                toolEnabled={toolByKey[source.key] ?? true}
                                entityOn={(entityId) => !!entityByKey[`${source.key}:${entityId}`]}
                                settingValue={(setting) => settingByKey[`${source.key}:${setting.key}`]}
                                onToggleArmed={() =>
                                    setArmedByKey((current) => ({ ...current, [source.key]: !current[source.key] }))
                                }
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
            ))}
        </div>
    )
}

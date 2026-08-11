import { useMemo, useState } from 'react'

import { IconArrowUpRight, IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSelect, LemonSwitch, LemonTag, Link } from '@posthog/lemon-ui'

import { LemonTagType } from 'lib/lemon-ui/LemonTag/LemonTag'

import { getSourceProductMeta } from '../../badges/sourceProductIcons'
import { LAB_GROUPS, LabSetting, LabSource, LabSourceKey, VariantProps } from './contract'

/**
 * Variant D: two-pane settings.
 *
 * The bet: this is a settings surface with real depth per item, and PostHog already solves that
 * shape with a source list on the left and the selected source in full on the right. Wider modal,
 * and the entity list is the only thing that ever scrolls.
 */
export const WIDTH_D = 1040

/** Above this many entities the list earns a filter box rather than only a scroll bar. */
const ENTITY_FILTER_THRESHOLD = 8

type SwitchState = Record<string, boolean>
type SettingState = Record<string, string | number | boolean>

function entityKey(source: LabSource, entityId: string): string {
    return `${source.key}:${entityId}`
}

function initialSwitchState(sources: LabSource[]): SwitchState {
    const state: SwitchState = {}
    for (const source of sources) {
        state[source.key] = source.armed
        for (const entity of source.entities ?? []) {
            state[entityKey(source, entity.id)] = entity.enabled
        }
    }
    return state
}

function initialSettingState(sources: LabSource[]): SettingState {
    const state: SettingState = {}
    for (const source of sources) {
        for (const setting of source.settings ?? []) {
            state[`${source.key}:${setting.key}`] = setting.value
        }
    }
    return state
}

/** A source with entities is on when any entity is on; otherwise its own switch decides. */
function sourceIsOn(source: LabSource, switchState: SwitchState): boolean {
    if (source.entities?.length) {
        return source.entities.some((entity) => switchState[entityKey(source, entity.id)])
    }
    return !!switchState[source.key]
}

function enabledCount(source: LabSource, switchState: SwitchState): number {
    return (source.entities ?? []).filter((entity) => switchState[entityKey(source, entity.id)]).length
}

function ProductIcon({ source, className }: { source: LabSource; className?: string }): JSX.Element | null {
    const meta = getSourceProductMeta(source.product)
    if (!meta) {
        return null
    }
    const Icon = meta.Icon
    return <Icon className={`shrink-0 ${meta.colorClass} ${className ?? 'text-base'}`} />
}

function StatusDot({ source, on, toolOn }: { source: LabSource; on: boolean; toolOn: boolean }): JSX.Element {
    const toolOff = !!source.tool && !toolOn
    let className = 'bg-border-bold'
    if (source.status === 'sync_failed') {
        className = 'bg-danger'
    } else if (toolOff && !on) {
        className = 'bg-warning'
    } else if (on) {
        className = source.status === 'syncing' ? 'bg-accent' : 'bg-success'
    }
    return <span className={`size-2 shrink-0 rounded-full ${className}`} />
}

function statusTag(source: LabSource, on: boolean, toolOn: boolean): { label: string; type: LemonTagType } {
    if (source.tool && !toolOn) {
        return { label: 'Tool off', type: 'warning' }
    }
    if (source.status === 'sync_failed') {
        return { label: 'Sync failed', type: 'danger' }
    }
    if (!on) {
        return { label: 'Standby', type: 'muted' }
    }
    if (source.status === 'syncing') {
        return { label: 'Syncing', type: 'primary' }
    }
    return { label: 'Watching', type: 'success' }
}

function receivingDataLabel(source: LabSource, on: boolean): string {
    if (!source.tool) {
        return 'Not tracked'
    }
    if (source.tool.receivingData === null) {
        return 'Not tracked'
    }
    if (!on) {
        return 'Paused'
    }
    return source.tool.receivingData ? 'Yes' : 'Nothing yet'
}

function Fact({ label, value }: { label: string; value: string }): JSX.Element {
    return (
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span className="text-xs text-muted">{label}</span>
            <span className="truncate text-xs font-medium text-default">{value}</span>
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
                onChange={(next: string) => onChange(next)}
            />
        )
    }
    return (
        <LemonInput
            type="number"
            size="xsmall"
            className="w-28"
            value={Number(value)}
            suffix={setting.suffix ? <span className="text-xs text-muted">{setting.suffix}</span> : undefined}
            onChange={(next) => onChange(next ?? 0)}
        />
    )
}

export function VariantD({ sources, scenario }: VariantProps): JSX.Element {
    const [switchState, setSwitchState] = useState<SwitchState>(() => initialSwitchState(sources))
    const [settingState, setSettingState] = useState<SettingState>(() => initialSettingState(sources))
    const [selectedKey, setSelectedKey] = useState<LabSourceKey>(sources[0].key)
    const [filter, setFilter] = useState('')
    // Tool state is local too, so the banner's "turn it on" unlocks the switches it was blocking.
    const [toolsOn, setToolsOn] = useState<Record<string, boolean>>(() =>
        Object.fromEntries(sources.map((source) => [source.key, !!source.tool?.enabled]))
    )
    const [syncRetried, setSyncRetried] = useState<Record<string, boolean>>({})

    const selected = useMemo(
        (): LabSource => sources.find((source) => source.key === selectedKey) ?? sources[0],
        [sources, selectedKey]
    )

    const onSources = sources.filter((source) => sourceIsOn(source, switchState))
    const watchedEntities = sources.reduce((total, source) => total + enabledCount(source, switchState), 0)

    const selectedOn = sourceIsOn(selected, switchState)
    const selectedEntities = selected.entities ?? []
    const selectedEnabled = enabledCount(selected, switchState)
    const toolOff = !!selected.tool && !toolsOn[selected.key]
    const armingBlocked = toolOff && !selectedOn
    const tag = statusTag(selected, selectedOn, !!toolsOn[selected.key])

    const query = filter.trim().toLowerCase()
    const visibleEntities = query
        ? selectedEntities.filter((entity) => entity.name.toLowerCase().includes(query))
        : selectedEntities

    const setEntity = (source: LabSource, entityId: string, next: boolean): void =>
        setSwitchState((state) => ({ ...state, [entityKey(source, entityId)]: next }))

    const setAllEntities = (source: LabSource, next: boolean): void =>
        setSwitchState((state) => {
            const updated = { ...state, [source.key]: next }
            for (const entity of source.entities ?? []) {
                updated[entityKey(source, entity.id)] = next
            }
            return updated
        })

    const masterChecked: boolean | 'indeterminate' = selectedEntities.length
        ? selectedEnabled === selectedEntities.length
            ? true
            : selectedEnabled > 0
              ? 'indeterminate'
              : false
        : !!switchState[selected.key]

    return (
        <div className="flex h-[560px] gap-4">
            <div className="flex w-64 shrink-0 flex-col gap-2 border-r border-primary pr-4">
                <div className="flex flex-col gap-0.5">
                    <span
                        className={`text-xs font-medium ${scenario === 'nothingOn' ? 'text-warning' : 'text-default'}`}
                    >
                        {onSources.length === 0
                            ? 'Nothing is watching yet'
                            : `${onSources.length} of ${sources.length} sources on`}
                    </span>
                    <span className="text-xs text-muted">
                        {watchedEntities === 0
                            ? 'Pick a source to turn something on'
                            : `${watchedEntities} watchers feeding the inbox`}
                    </span>
                </div>
                {LAB_GROUPS.map((group) => (
                    <div key={group} className="flex flex-col gap-0.5">
                        <span className="px-1 text-xs text-muted">{group}</span>
                        {sources
                            .filter((source) => source.group === group)
                            .map((source) => {
                                const on = sourceIsOn(source, switchState)
                                const isSelected = source.key === selected.key
                                return (
                                    <LemonButton
                                        key={source.key}
                                        size="small"
                                        fullWidth
                                        active={isSelected}
                                        className={isSelected ? 'bg-accent-highlight-secondary' : undefined}
                                        icon={<ProductIcon source={source} className="text-sm" />}
                                        onClick={() => {
                                            setSelectedKey(source.key)
                                            setFilter('')
                                        }}
                                    >
                                        <div className="flex min-w-0 flex-1 items-center gap-2">
                                            <span
                                                className={`truncate text-sm ${on ? 'text-default' : 'text-secondary'}`}
                                            >
                                                {source.label}
                                            </span>
                                            <div className="flex-1" />
                                            {!!source.entities?.length && (
                                                <span className="shrink-0 text-xs text-muted">
                                                    {enabledCount(source, switchState)}/{source.entities.length}
                                                </span>
                                            )}
                                            <StatusDot source={source} on={on} toolOn={!!toolsOn[source.key]} />
                                        </div>
                                    </LemonButton>
                                )
                            })}
                    </div>
                ))}
            </div>

            <div className="flex min-w-0 flex-1 flex-col gap-3">
                <div className="flex items-start gap-3">
                    <ProductIcon source={selected} className="mt-1 text-xl" />
                    <div className="flex min-w-0 flex-1 flex-col gap-1">
                        <div className="flex flex-wrap items-center gap-2">
                            <span className="text-base font-semibold text-default">{selected.label}</span>
                            <LemonTag size="small" type={tag.type}>
                                {tag.label}
                            </LemonTag>
                            {selected.alpha && (
                                <LemonTag size="small" type="completion">
                                    Alpha
                                </LemonTag>
                            )}
                            {selected.legacy && (
                                <LemonTag size="small" type="caution">
                                    Legacy
                                </LemonTag>
                            )}
                        </div>
                        <p className="mb-0 text-xs text-secondary">
                            {selected.description}{' '}
                            {selected.docsUrl && (
                                <Link to={selected.docsUrl} target="_blank" className="whitespace-nowrap text-xs">
                                    Learn about {selected.docsLabel ?? selected.label}
                                    <IconArrowUpRight />
                                </Link>
                            )}
                        </p>
                    </div>
                    <div className="shrink-0 pt-1">
                        {selected.requiresSetup ? (
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={() => setSwitchState((state) => ({ ...state, [selected.key]: true }))}
                            >
                                Connect
                            </LemonButton>
                        ) : (
                            <LemonSwitch
                                size="small"
                                checked={masterChecked}
                                onChange={(next) =>
                                    selectedEntities.length
                                        ? setAllEntities(selected, next)
                                        : setSwitchState((state) => ({ ...state, [selected.key]: next }))
                                }
                                disabledReason={
                                    armingBlocked
                                        ? `Turn on ${selected.tool?.name} first. This source reads its data.`
                                        : undefined
                                }
                                aria-label={`Turn on ${selected.label}`}
                            />
                        )}
                    </div>
                </div>

                {toolOff && selected.tool && (
                    <LemonBanner
                        type="warning"
                        action={{
                            children: 'Turn it on',
                            onClick: () => setToolsOn((state) => ({ ...state, [selected.key]: true })),
                        }}
                    >
                        <span className="text-xs">
                            {selected.tool.name} is off, so this source has nothing to read.
                        </span>
                    </LemonBanner>
                )}
                {selected.status === 'sync_failed' && !syncRetried[selected.key] && (
                    <LemonBanner
                        type="error"
                        action={{
                            children: 'Retry',
                            onClick: () => setSyncRetried((state) => ({ ...state, [selected.key]: true })),
                        }}
                    >
                        <span className="text-xs">The last sync failed, so nothing new has arrived.</span>
                    </LemonBanner>
                )}

                <div className="flex gap-4 rounded border border-primary bg-surface-secondary px-3 py-2">
                    <Fact
                        label="Watching"
                        value={
                            selectedEntities.length
                                ? `${selectedEnabled} of ${selectedEntities.length} ${selected.entityNoun ?? 'watchers'}`
                                : selectedOn
                                  ? 'On'
                                  : 'Off'
                        }
                    />
                    <Fact
                        label="Tool"
                        value={selected.tool ? `${selected.tool.name}, ${toolOff ? 'off' : 'on'}` : 'None needed'}
                    />
                    <Fact label="Receiving data" value={receivingDataLabel(selected, selectedOn && !toolOff)} />
                </div>

                {!!selected.settings?.length && (
                    <div className="flex flex-col gap-2">
                        <span className="text-xs font-medium text-muted">Settings</span>
                        {selected.settings.map((setting) => (
                            <div key={setting.key} className="flex items-center gap-3">
                                <div className="flex min-w-0 flex-1 flex-col">
                                    <span className="text-sm text-default">{setting.label}</span>
                                    {setting.help && <span className="text-xs text-muted">{setting.help}</span>}
                                </div>
                                <SettingControl
                                    setting={setting}
                                    value={settingState[`${selected.key}:${setting.key}`] ?? setting.value}
                                    onChange={(next) =>
                                        setSettingState((state) => ({
                                            ...state,
                                            [`${selected.key}:${setting.key}`]: next,
                                        }))
                                    }
                                />
                            </div>
                        ))}
                    </div>
                )}

                {selectedEntities.length === 0 ? (
                    <div className="rounded border border-dashed border-primary px-3 py-3">
                        <span className="text-xs text-secondary">
                            Nothing to pick here. {selected.label} watches everything it can see, so the switch above is
                            the whole control.
                        </span>
                    </div>
                ) : (
                    <>
                        <div className="flex items-center gap-2">
                            <span className="text-xs font-medium text-muted">
                                {selectedEnabled} of {selectedEntities.length} {selected.entityNoun ?? 'watchers'} on
                            </span>
                            {selectedEntities.length > ENTITY_FILTER_THRESHOLD && (
                                <>
                                    <LemonInput
                                        type="search"
                                        size="xsmall"
                                        className="w-52"
                                        placeholder={`Filter ${selected.entityNoun ?? 'watchers'}`}
                                        value={filter}
                                        onChange={setFilter}
                                    />
                                    <span className="text-xs text-muted">
                                        {visibleEntities.length} of {selectedEntities.length}
                                    </span>
                                </>
                            )}
                            <div className="flex-1" />
                            {selected.entityManageUrl && (
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    to={selected.entityManageUrl}
                                    icon={<IconPlus />}
                                    targetBlank
                                >
                                    New {selected.entityNounSingular}
                                </LemonButton>
                            )}
                        </div>
                        {/* The only scrolling region, so the header, the settings and the left pane stay put. */}
                        <div className="min-h-0 flex-1 divide-y divide-primary overflow-y-auto rounded border border-primary">
                            {visibleEntities.length === 0 ? (
                                <p className="mb-0 px-3 py-6 text-center text-xs text-muted">
                                    No {selected.entityNoun ?? 'watchers'} match that filter.
                                </p>
                            ) : (
                                visibleEntities.map((entity) => {
                                    const on = !!switchState[entityKey(selected, entity.id)]
                                    return (
                                        <div
                                            key={entity.id}
                                            className="flex items-start gap-2.5 px-3 py-2 hover:bg-surface-secondary"
                                        >
                                            <div className="pt-0.5">
                                                <LemonSwitch
                                                    size="xxsmall"
                                                    checked={on}
                                                    onChange={(next) => setEntity(selected, entity.id, next)}
                                                    disabledReason={
                                                        toolOff && !on
                                                            ? `Turn on ${selected.tool?.name} first. This source reads its data.`
                                                            : undefined
                                                    }
                                                    aria-label={entity.name}
                                                />
                                            </div>
                                            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                                                <div className="flex min-w-0 items-center gap-2">
                                                    <span
                                                        className={`truncate text-sm leading-5 ${
                                                            on ? 'font-medium text-default' : 'text-secondary'
                                                        }`}
                                                    >
                                                        {entity.name}
                                                    </span>
                                                    {entity.kind && (
                                                        <LemonTag size="small" type="muted">
                                                            {entity.kind}
                                                        </LemonTag>
                                                    )}
                                                </div>
                                                {entity.detail && (
                                                    <span className="truncate text-xs leading-4 text-muted">
                                                        {entity.detail}
                                                    </span>
                                                )}
                                                {entity.systemNote && (
                                                    <span className="text-xs leading-4 text-warning">
                                                        {entity.systemNote}
                                                    </span>
                                                )}
                                            </div>
                                        </div>
                                    )
                                })
                            )}
                        </div>
                    </>
                )}
            </div>
        </div>
    )
}

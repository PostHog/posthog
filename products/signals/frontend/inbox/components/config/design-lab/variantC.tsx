import { useMemo, useState } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import { getSourceProductMeta } from '../../badges/sourceProductIcons'
import { LAB_GROUPS, LabSource, LabSourceKey, VariantProps } from './contract'

/**
 * Variant C: watcher-first list.
 *
 * The bet: the product category is not the unit a person manages, the individual watcher is. So the
 * panel is one flat list of watchers, and products only reappear as a quiet parking area for the
 * ones with nothing on.
 */
export const WIDTH_C = 760

/** Rows one product may take in the flat list before the rest fold away. A search lifts the cap. */
const ROWS_PER_PRODUCT = 6

/** One switchable thing: an entity, or the whole source when it has no entities. */
interface Watcher {
    key: string
    source: LabSource
    name: string
    detail?: string
    kind?: string
    systemNote?: string
}

function watchersOf(source: LabSource): Watcher[] {
    if (source.entities?.length) {
        return source.entities.map((entity) => ({
            key: `${source.key}:${entity.id}`,
            source,
            name: entity.name,
            detail: entity.detail,
            kind: entity.kind,
            systemNote: entity.systemNote,
        }))
    }
    return [
        {
            key: source.key,
            source,
            name: source.label,
            detail: source.description,
            kind: 'Whole product',
        },
    ]
}

function initialSwitchState(sources: LabSource[]): Record<string, boolean> {
    const state: Record<string, boolean> = {}
    for (const source of sources) {
        if (source.entities?.length) {
            for (const entity of source.entities) {
                state[`${source.key}:${entity.id}`] = entity.enabled
            }
        } else {
            state[source.key] = source.armed
        }
    }
    return state
}

function productLabel(source: LabSource): string {
    return getSourceProductMeta(source.product)?.label ?? source.label
}

function matchesQuery(watcher: Watcher, query: string): boolean {
    if (!query) {
        return true
    }
    return [watcher.name, productLabel(watcher.source), watcher.kind ?? ''].some((field) =>
        field.toLowerCase().includes(query)
    )
}

function ProductIcon({ source, className }: { source: LabSource; className?: string }): JSX.Element | null {
    const meta = getSourceProductMeta(source.product)
    if (!meta) {
        return null
    }
    const Icon = meta.Icon
    return <Icon className={`shrink-0 ${meta.colorClass} ${className ?? 'text-base'}`} />
}

function toolBlockReason(source: LabSource, on: boolean): string | undefined {
    if (on || !source.tool || source.tool.enabled) {
        return undefined
    }
    return `Turn on ${source.tool.name} first. This source reads its data.`
}

function WatcherRow({ watcher, on, onToggle }: { watcher: Watcher; on: boolean; onToggle: () => void }): JSX.Element {
    return (
        <div className="flex items-start gap-2.5 px-2 py-2 hover:bg-surface-secondary">
            <ProductIcon source={watcher.source} className="mt-0.5 text-base" />
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <div className="flex min-w-0 items-center gap-2">
                    <span
                        className={`truncate text-sm leading-5 ${on ? 'font-medium text-default' : 'text-secondary'}`}
                    >
                        {watcher.name}
                    </span>
                    {watcher.kind && (
                        <LemonTag size="small" type="muted">
                            {watcher.kind}
                        </LemonTag>
                    )}
                </div>
                <span className="truncate text-xs leading-4 text-muted">
                    {productLabel(watcher.source)}
                    {watcher.detail ? ` · ${watcher.detail}` : ''}
                </span>
                {watcher.systemNote && <span className="text-xs leading-4 text-warning">{watcher.systemNote}</span>}
            </div>
            <div className="pt-1">
                <LemonSwitch
                    size="xsmall"
                    checked={on}
                    onChange={onToggle}
                    disabledReason={toolBlockReason(watcher.source, on)}
                    aria-label={watcher.name}
                />
            </div>
        </div>
    )
}

export function VariantC({ sources, scenario }: VariantProps): JSX.Element {
    const [switchState, setSwitchState] = useState<Record<string, boolean>>(() => initialSwitchState(sources))
    const [search, setSearch] = useState('')
    const [hideOff, setHideOff] = useState(false)
    const [uncapped, setUncapped] = useState<Record<string, boolean>>({})
    const [openProducts, setOpenProducts] = useState<Record<string, boolean>>({})

    const byProduct = useMemo(
        (): { source: LabSource; watchers: Watcher[] }[] =>
            sources.map((source) => ({ source, watchers: watchersOf(source) })),
        [sources]
    )

    const toggle = (key: string): void => setSwitchState((state) => ({ ...state, [key]: !state[key] }))
    const setProductOpen = (key: LabSourceKey): void => setOpenProducts((state) => ({ ...state, [key]: !state[key] }))

    const allWatchers = byProduct.flatMap((entry) => entry.watchers)
    const onCount = allWatchers.filter((watcher) => switchState[watcher.key]).length
    const watching = byProduct.filter((entry) => entry.watchers.some((watcher) => switchState[watcher.key]))
    const idle = byProduct.filter((entry) => !entry.watchers.some((watcher) => switchState[watcher.key]))

    const query = search.trim().toLowerCase()
    const blocks = watching
        .map(({ source, watchers }) => {
            const visible = watchers.filter(
                (watcher) => (!hideOff || switchState[watcher.key]) && matchesQuery(watcher, query)
            )
            // Searching is already a narrowing, so it lifts the per-product cap.
            const capped = query || uncapped[source.key] ? visible : visible.slice(0, ROWS_PER_PRODUCT)
            return { source, visible, capped }
        })
        .filter((block) => block.visible.length > 0)

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-0.5">
                <span className="text-sm font-medium text-default">
                    {onCount} of {allWatchers.length} watchers on
                </span>
                <span className="text-xs text-muted">
                    {watching.length} {watching.length === 1 ? 'product' : 'products'} watching, {idle.length} not
                    watching yet
                </span>
            </div>

            <div className="flex items-center gap-3">
                <LemonInput
                    type="search"
                    size="small"
                    className="w-72"
                    placeholder="Search watchers, products, kinds"
                    value={search}
                    onChange={setSearch}
                />
                <div className="flex-1" />
                <LemonSwitch
                    size="xsmall"
                    checked={hideOff}
                    onChange={setHideOff}
                    label={<span className="text-xs text-secondary">Hide off watchers</span>}
                />
            </div>

            {blocks.length === 0 ? (
                <div className="flex flex-col items-start gap-1 rounded border border-dashed border-primary bg-surface-secondary px-4 py-5">
                    <span className="text-sm font-medium text-default">
                        {onCount === 0 ? 'Nothing is watching yet' : 'No watchers match that search'}
                    </span>
                    <span className="text-xs text-secondary">
                        {onCount === 0
                            ? scenario === 'nothingOn'
                                ? 'Turn on a watcher below and its findings start landing in your inbox.'
                                : 'Everything is off. Turn a watcher back on below.'
                            : 'Clear the search to see everything that is on.'}
                    </span>
                </div>
            ) : (
                <div className="divide-y divide-primary overflow-hidden rounded border border-primary">
                    {blocks.map(({ source, visible, capped }) => (
                        <div key={source.key} className="divide-y divide-primary">
                            {capped.map((watcher) => (
                                <WatcherRow
                                    key={watcher.key}
                                    watcher={watcher}
                                    on={!!switchState[watcher.key]}
                                    onToggle={() => toggle(watcher.key)}
                                />
                            ))}
                            {visible.length > capped.length && (
                                <LemonButton
                                    size="xsmall"
                                    type="tertiary"
                                    fullWidth
                                    onClick={() => setUncapped((state) => ({ ...state, [source.key]: true }))}
                                >
                                    <span className="text-xs text-accent">
                                        Show {visible.length - capped.length} more {source.entityNoun ?? 'watchers'} in{' '}
                                        {source.label}
                                    </span>
                                </LemonButton>
                            )}
                            {!query && uncapped[source.key] && visible.length > ROWS_PER_PRODUCT && (
                                <LemonButton
                                    size="xsmall"
                                    type="tertiary"
                                    fullWidth
                                    onClick={() => setUncapped((state) => ({ ...state, [source.key]: false }))}
                                >
                                    <span className="text-xs text-accent">
                                        Show fewer {source.entityNoun ?? 'watchers'} in {source.label}
                                    </span>
                                </LemonButton>
                            )}
                        </div>
                    ))}
                </div>
            )}

            {idle.length > 0 && (
                <div className="flex flex-col gap-2 border-t border-primary pt-3">
                    <span className="text-xs font-medium text-muted">Not watching yet</span>
                    {LAB_GROUPS.map((group) => {
                        const groupEntries = idle.filter((entry) => entry.source.group === group)
                        if (groupEntries.length === 0) {
                            return null
                        }
                        return (
                            <div key={group} className="flex flex-col gap-1">
                                <span className="text-xs text-muted">{group}</span>
                                <div className="divide-y divide-primary overflow-hidden rounded border border-primary bg-surface-secondary">
                                    {groupEntries.map(({ source, watchers }) => {
                                        const expandable = !source.requiresSetup && !!source.entities?.length
                                        const open = !!openProducts[source.key]
                                        const shown = open ? watchers.slice(0, ROWS_PER_PRODUCT) : []
                                        return (
                                            <div key={source.key}>
                                                <div className="flex items-center gap-2.5 px-2 py-2">
                                                    <ProductIcon source={source} />
                                                    <div className="flex min-w-0 flex-1 flex-col">
                                                        <div className="flex items-center gap-2">
                                                            <span className="truncate text-sm leading-5 text-secondary">
                                                                {source.label}
                                                            </span>
                                                            {source.status === 'sync_failed' && (
                                                                <LemonTag size="small" type="danger">
                                                                    Sync failed
                                                                </LemonTag>
                                                            )}
                                                            {source.alpha && (
                                                                <LemonTag size="small" type="completion">
                                                                    Alpha
                                                                </LemonTag>
                                                            )}
                                                            {source.legacy && (
                                                                <LemonTag size="small" type="caution">
                                                                    Legacy
                                                                </LemonTag>
                                                            )}
                                                        </div>
                                                        <span className="truncate text-xs leading-4 text-muted">
                                                            {source.entities?.length
                                                                ? `${source.entities.length} ${source.entityNoun ?? 'watchers'}, none on`
                                                                : source.description}
                                                        </span>
                                                    </div>
                                                    {source.requiresSetup ? (
                                                        <LemonButton
                                                            type="secondary"
                                                            size="xsmall"
                                                            onClick={() => toggle(source.key)}
                                                        >
                                                            Connect
                                                        </LemonButton>
                                                    ) : expandable ? (
                                                        <LemonButton
                                                            size="xsmall"
                                                            type="tertiary"
                                                            onClick={() => setProductOpen(source.key)}
                                                            sideIcon={
                                                                <IconChevronRight
                                                                    className={`transition-transform ${open ? 'rotate-90' : ''}`}
                                                                />
                                                            }
                                                        >
                                                            {open ? 'Hide' : 'Pick'} {source.entityNoun ?? 'watchers'}
                                                        </LemonButton>
                                                    ) : (
                                                        <LemonSwitch
                                                            size="xsmall"
                                                            checked={!!switchState[source.key]}
                                                            onChange={() => toggle(source.key)}
                                                            disabledReason={toolBlockReason(source, false)}
                                                            aria-label={`Turn on ${source.label}`}
                                                        />
                                                    )}
                                                </div>
                                                {open && (
                                                    <div className="divide-y divide-primary border-t border-primary bg-surface-primary pl-6">
                                                        {shown.map((watcher) => (
                                                            <WatcherRow
                                                                key={watcher.key}
                                                                watcher={watcher}
                                                                on={!!switchState[watcher.key]}
                                                                onToggle={() => toggle(watcher.key)}
                                                            />
                                                        ))}
                                                        {watchers.length > shown.length && (
                                                            <span className="block px-2 py-1.5 text-xs text-muted">
                                                                {watchers.length - shown.length} more{' '}
                                                                {source.entityNoun ?? 'watchers'} here. Turn one on to
                                                                move {source.label} up.
                                                            </span>
                                                        )}
                                                    </div>
                                                )}
                                            </div>
                                        )
                                    })}
                                </div>
                            </div>
                        )
                    })}
                </div>
            )}
        </div>
    )
}

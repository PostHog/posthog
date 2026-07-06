import { CSSProperties, useMemo } from 'react'
import { List } from 'react-window'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

const ROW_HEIGHT = 33

export interface FacetOption {
    value: string
    label: string
    /** Tailwind bg class for a leading color swatch (e.g. severity colors). */
    color?: string
    /** Number of matching log records; rendered right-aligned. Omitted when unavailable. */
    count?: number
}

interface FacetProps {
    title: string
    options: FacetOption[]
    selected: string[]
    onToggle: (value: string) => void
    loading?: boolean
    emptyLabel?: string
    /** When provided, renders a search box above the values (state owned by the caller). */
    searchValue?: string
    onSearchChange?: (value: string) => void
    searchPlaceholder?: string
    collapsed?: boolean
    onToggleCollapsed?: () => void
    /** When set, values render in a fixed-height virtualized list capped at this many pixels. */
    maxHeight?: number
    /** For fixed facets: render zero-count values dimmed, and disabled unless already selected. */
    dimZeroCounts?: boolean
}

/** A single rail facet: a collapsible field title and its selectable values (multi-select = OR), each with a count. */
export function Facet({
    title,
    options,
    selected,
    onToggle,
    loading = false,
    emptyLabel = 'No values',
    searchValue,
    onSearchChange,
    searchPlaceholder = 'Search…',
    collapsed = false,
    onToggleCollapsed,
    maxHeight,
    dimZeroCounts = false,
}: FacetProps): JSX.Element {
    const slug = title.toLowerCase().replace(/\s+/g, '-')

    const rowProps = useMemo<FacetValueRowProps>(
        () => ({ options, selected, slug, onToggle, dimZeroCounts }),
        [options, selected, slug, onToggle, dimZeroCounts]
    )

    return (
        <div className="mb-3">
            <button
                type="button"
                onClick={onToggleCollapsed}
                disabled={!onToggleCollapsed}
                className="flex items-center gap-1 w-full px-1 mb-1 text-[10px] font-semibold uppercase tracking-wide text-secondary hover:text-default"
                data-attr={`logs-facet-${slug}-header`}
            >
                {collapsed ? <IconChevronRight /> : <IconChevronDown />}
                <span>{title}</span>
            </button>
            {!collapsed && onSearchChange && (
                <div className="px-1 pb-1">
                    <LemonInput
                        type="search"
                        size="small"
                        fullWidth
                        placeholder={searchPlaceholder}
                        value={searchValue ?? ''}
                        onChange={onSearchChange}
                    />
                </div>
            )}
            {!collapsed &&
                (loading && options.length === 0 ? (
                    <div className="px-1 text-xs text-muted">Loading…</div>
                ) : options.length === 0 ? (
                    <div className="px-1 text-xs text-muted">{emptyLabel}</div>
                ) : (
                    // Dim the list while a refetch is in flight (e.g. typing in search) so there's
                    // feedback that results are updating, rather than the list silently changing.
                    <div className={cn(loading && 'opacity-60 transition-opacity')}>
                        {maxHeight ? (
                            <List<FacetValueRowProps>
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ width: '100%', height: Math.min(options.length * ROW_HEIGHT, maxHeight) }}
                                rowCount={options.length}
                                rowHeight={ROW_HEIGHT}
                                overscanCount={5}
                                rowComponent={FacetValueRow}
                                rowProps={rowProps}
                            />
                        ) : (
                            <div className="space-y-px">
                                {options.map((option) => (
                                    <FacetValueButton
                                        key={option.value}
                                        option={option}
                                        selected={selected.includes(option.value)}
                                        slug={slug}
                                        onToggle={onToggle}
                                        dimZeroCounts={dimZeroCounts}
                                    />
                                ))}
                            </div>
                        )}
                    </div>
                ))}
        </div>
    )
}

interface FacetValueRowProps {
    options: FacetOption[]
    selected: string[]
    slug: string
    onToggle: (value: string) => void
    dimZeroCounts: boolean
}

function FacetValueRow({
    index,
    style,
    options,
    selected,
    slug,
    onToggle,
    dimZeroCounts,
}: {
    ariaAttributes: Record<string, unknown>
    index: number
    style: CSSProperties
} & FacetValueRowProps): JSX.Element {
    const option = options[index]
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={style}>
            <FacetValueButton
                option={option}
                selected={selected.includes(option.value)}
                slug={slug}
                onToggle={onToggle}
                dimZeroCounts={dimZeroCounts}
            />
        </div>
    )
}

function FacetValueButton({
    option,
    selected,
    slug,
    onToggle,
    dimZeroCounts,
}: {
    option: FacetOption
    selected: boolean
    slug: string
    onToggle: (value: string) => void
    dimZeroCounts: boolean
}): JSX.Element {
    // A fixed facet value with no matches in the current scope: dim it, and disable it unless it's
    // already selected (so a selected-but-now-empty value can still be toggled off).
    const isZero = dimZeroCounts && option.count === 0
    return (
        <LemonButton
            type="tertiary"
            size="small"
            fullWidth
            className={cn(isZero && 'opacity-50')}
            disabledReason={isZero && !selected ? 'No matching logs for the current filters' : undefined}
            icon={<LemonCheckbox checked={selected} className="pointer-events-none" />}
            onClick={() => onToggle(option.value)}
            data-attr={`logs-facet-${slug}-${option.value}`}
        >
            <span className="flex items-center gap-2 min-w-0 w-full">
                {option.color && <span className={cn('w-1 h-3.5 rounded-full shrink-0', option.color)} />}
                <span className="truncate flex-1">{option.label}</span>
                {option.count != null && (
                    <span className="shrink-0 text-muted tabular-nums">{humanFriendlyLargeNumber(option.count)}</span>
                )}
            </span>
        </LemonButton>
    )
}

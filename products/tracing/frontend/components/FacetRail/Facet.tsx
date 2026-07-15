import { CSSProperties, useMemo } from 'react'
import { List } from 'react-window'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { FacetOption } from './facets'

const ROW_HEIGHT = 33

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
    /** The facet's latest fetch failed — show an inline error instead of pretending the list is fresh (suppresses emptyLabel). */
    error?: boolean
}

/**
 * Lowercase a label into a selector-safe slug for data-attrs. Facet values are real resource
 * attributes (pod, deployment, host names) that can carry spaces, quotes, or slashes, so collapse
 * any run of non-alphanumerics to a single hyphen and trim the ends.
 */
function slugify(value: string): string {
    return value
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '')
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
    error = false,
}: FacetProps): JSX.Element {
    const slug = slugify(title)

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
                data-attr={`tracing-facet-${slug}-header`}
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
            {/* A failed fetch shows inline (options may be stale-but-usable below) rather than blanking the facet. */}
            {!collapsed && error && !loading && (
                <div className="px-1 pb-1 text-xs text-danger" data-attr={`tracing-facet-${slug}-error`}>
                    Couldn't load values
                </div>
            )}
            {!collapsed &&
                (loading && options.length === 0 ? (
                    <div className="px-1 text-xs text-muted">Loading…</div>
                ) : options.length === 0 ? (
                    // The error line above already explains the missing values — don't add "No values".
                    !error && <div className="px-1 text-xs text-muted">{emptyLabel}</div>
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
    ariaAttributes,
    index,
    style,
    options,
    selected,
    slug,
    onToggle,
    dimZeroCounts,
}: {
    ariaAttributes: { 'aria-posinset': number; 'aria-setsize': number; role: 'listitem' }
    index: number
    style: CSSProperties
} & FacetValueRowProps): JSX.Element {
    const option = options[index]
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={style} {...ariaAttributes}>
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
            disabledReason={isZero && !selected ? 'No matching spans for the current filters' : undefined}
            icon={<LemonCheckbox checked={selected} className="pointer-events-none" />}
            onClick={() => onToggle(option.value)}
            data-attr={`tracing-facet-${slug}-${slugify(option.value)}`}
        >
            <span className="flex items-center gap-2 min-w-0 w-full">
                {/* Native title so a truncated value is still readable without popover cost per virtualized row. */}
                <span className="truncate flex-1" title={option.label}>
                    {option.label}
                </span>
                {option.count != null && (
                    <span className="shrink-0 text-muted tabular-nums">{humanFriendlyLargeNumber(option.count)}</span>
                )}
            </span>
        </LemonButton>
    )
}

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonCheckbox } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { FacetOption } from './facets'

interface FacetProps {
    title: string
    options: FacetOption[]
    selected: string[]
    onToggle: (value: string) => void
    loading?: boolean
    emptyLabel?: string
    collapsed?: boolean
    onToggleCollapsed?: () => void
    /** For fixed facets: render zero-count values dimmed, and disabled unless already selected. */
    dimZeroCounts?: boolean
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
    collapsed = false,
    onToggleCollapsed,
    dimZeroCounts = false,
}: FacetProps): JSX.Element {
    const slug = slugify(title)

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
            {!collapsed &&
                (loading && options.length === 0 ? (
                    <div className="px-1 text-xs text-muted">Loading…</div>
                ) : options.length === 0 ? (
                    <div className="px-1 text-xs text-muted">{emptyLabel}</div>
                ) : (
                    // Dim the list while a refetch is in flight so there's feedback that results
                    // are updating, rather than the list silently changing.
                    <div className={cn('space-y-px', loading && 'opacity-60 transition-opacity')}>
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
                ))}
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
                <span className="truncate flex-1">{option.label}</span>
                {option.count != null && (
                    <span className="shrink-0 text-muted tabular-nums">{humanFriendlyLargeNumber(option.count)}</span>
                )}
            </span>
        </LemonButton>
    )
}

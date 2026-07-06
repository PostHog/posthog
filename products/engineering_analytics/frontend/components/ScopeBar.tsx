// Shared scope bar: hierarchy chips (repo › workflow › run) on the left, dismissible filter chips on
// the right, and the shared branch/date scope (engineeringAnalyticsFiltersLogic) so a window picked on
// one page carries to the next.

import { useActions, useValues } from 'kea'
import { Fragment, ReactNode, useState } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonInput, LemonSelect, Link } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { cn } from 'lib/utils/css-classes'
import { dateMapping } from 'lib/utils/dateFilters'

import { SHARED_DEFAULT_DATE_FROM, engineeringAnalyticsFiltersLogic } from '../scenes/engineeringAnalyticsFiltersLogic'
import { engineeringAnalyticsLogic } from '../scenes/engineeringAnalyticsLogic'

// The endpoints require a window start (no "all time") — relative windows + Custom only.
export const SCOPE_DATE_OPTIONS = dateMapping.filter(({ key }) =>
    [
        'Custom',
        'Last 24 hours',
        'Last 7 days',
        'Last 14 days',
        'Last 30 days',
        'Last 90 days',
        'Last 180 days',
    ].includes(key)
)

export interface ScopeCrumb {
    label: string
    to?: string
}

export interface LensChip {
    label: string
    /** Where dismissing the chip navigates. */
    to: string
}

const CHIP_CLASS =
    'inline-flex items-center gap-1.5 rounded border border-primary bg-surface-primary px-2.5 py-1 text-xs text-secondary'

/** A source picker on multi-source teams, otherwise the repo name. `pickerOnly` skips the static chip
 *  on pages that already state the repo elsewhere (the hub's entity header). */
export function SourceScopeChip({ pickerOnly = false }: { pickerOnly?: boolean }): JSX.Element | null {
    const { hasMultipleSources, sourceOptions, sourceId, activeSource } = useValues(engineeringAnalyticsLogic)
    const { setSourceId } = useActions(engineeringAnalyticsLogic)
    const repoLabel = activeSource?.repo
    if (hasMultipleSources) {
        return (
            <LemonSelect
                size="small"
                value={sourceId}
                onChange={setSourceId}
                options={sourceOptions}
                placeholder={repoLabel || 'Repository'}
                allowClear
                dropdownMatchSelectWidth={false}
                data-attr="engineering-analytics-source-select"
            />
        )
    }
    // No repo name yet — render nothing rather than a dead "Repository" pill.
    if (pickerOnly || !repoLabel) {
        return null
    }
    return (
        <span className={CHIP_CLASS}>
            <strong className="font-semibold text-primary">{repoLabel}</strong>
        </span>
    )
}

/** Repo chip on detail pages: links back to the hub without mounting the hub's loaders. */
export function RepoScopeChip({ label, to }: { label: string; to: string }): JSX.Element {
    return (
        <Link to={to}>
            <span className={cn(CHIP_CLASS, 'cursor-pointer')}>
                <strong className="font-semibold text-primary">{label}</strong>
            </span>
        </Link>
    )
}

// Quick presets for the default branch. We can't tell main from master without another query, so offer
// both — picking the active one clears back to all branches.
const DEFAULT_BRANCHES = ['main', 'master']

/** Branch chip opening a small picker — a server-side head_branch filter shared across pages. */
function BranchScopeChip(): JSX.Element {
    const { branchInput, appliedBranch } = useValues(engineeringAnalyticsFiltersLogic)
    const { setBranchFilter, applyBranchFilter } = useActions(engineeringAnalyticsFiltersLogic)
    const [visible, setVisible] = useState(false)

    // Stage + apply a branch in one click; picking the active preset clears back to all branches.
    const selectBranch = (branch: string): void => {
        setBranchFilter(branch)
        applyBranchFilter()
        setVisible(false)
    }

    return (
        <LemonDropdown
            visible={visible}
            onVisibilityChange={setVisible}
            closeOnClickInside={false}
            overlay={
                <div className="flex w-64 flex-col gap-2 p-1">
                    <LemonInput
                        type="search"
                        size="small"
                        placeholder="Branch name (exact)"
                        value={branchInput}
                        onChange={setBranchFilter}
                        onPressEnter={() => {
                            applyBranchFilter()
                            setVisible(false)
                        }}
                        autoFocus
                        data-attr="engineering-analytics-branch-filter"
                    />
                    <div className="flex flex-wrap gap-1">
                        {DEFAULT_BRANCHES.map((branch) => (
                            <LemonButton
                                key={branch}
                                size="xsmall"
                                type={appliedBranch === branch ? 'primary' : 'secondary'}
                                onClick={() => selectBranch(appliedBranch === branch ? '' : branch)}
                            >
                                {branch}
                            </LemonButton>
                        ))}
                        <LemonButton
                            size="xsmall"
                            type={appliedBranch === '' ? 'primary' : 'secondary'}
                            onClick={() => selectBranch('')}
                        >
                            all branches
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <span className={cn(CHIP_CLASS, 'cursor-pointer')} title="One branch scope for every section below">
                branch:{' '}
                <strong className={cn('font-semibold', appliedBranch ? 'text-primary' : 'text-tertiary')}>
                    {appliedBranch || 'all'}
                </strong>
                <span className="text-[8px] text-tertiary">▼</span>
            </span>
        </LemonDropdown>
    )
}

export function ScopeBar({
    repoSlot,
    crumbs = [],
    lensFilter,
    showBranch = false,
    showDate = true,
    extra,
}: {
    /** The repo chip: <SourceScopeChip /> on hub/list pages, <RepoScopeChip /> on detail pages. */
    repoSlot: ReactNode
    /** Hierarchy below the repo (workflow › run); empty on the repo hub itself. */
    crumbs?: ScopeCrumb[]
    /** The active cross-cutting lens (pr: #N) — dismissible, zooms out to `to`. */
    lensFilter?: LensChip
    showBranch?: boolean
    showDate?: boolean
    extra?: ReactNode
}): JSX.Element {
    const { dateFrom, dateTo } = useValues(engineeringAnalyticsFiltersLogic)
    const { setDateRange } = useActions(engineeringAnalyticsFiltersLogic)

    return (
        <div className="flex flex-wrap items-center gap-2">
            {repoSlot}
            {crumbs.map((crumb) => (
                <Fragment key={crumb.label}>
                    <span className="text-xs text-tertiary">›</span>
                    {crumb.to ? (
                        <Link to={crumb.to} className="text-[13px] font-medium">
                            {crumb.label}
                        </Link>
                    ) : (
                        <span className="text-[13px] font-semibold">{crumb.label}</span>
                    )}
                </Fragment>
            ))}
            <span className="ml-auto flex flex-wrap items-center gap-2">
                {lensFilter && (
                    <span
                        className={cn(CHIP_CLASS, 'border-accent-highlight-secondary bg-fill-highlight-50')}
                        title="A filter is applied to this page. Remove it to see the whole repo."
                    >
                        <strong className="font-semibold text-primary">{lensFilter.label}</strong>
                        <Link to={lensFilter.to} className="px-0.5 text-tertiary hover:text-primary">
                            <IconX />
                        </Link>
                    </span>
                )}
                {showBranch && <BranchScopeChip />}
                {showDate && (
                    <DateFilter
                        dateFrom={dateFrom}
                        dateTo={dateTo}
                        onChange={(from, to) => setDateRange(from ?? SHARED_DEFAULT_DATE_FROM, to ?? null)}
                        dateOptions={SCOPE_DATE_OPTIONS}
                        size="small"
                    />
                )}
                {extra}
            </span>
        </div>
    )
}

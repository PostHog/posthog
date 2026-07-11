// Shared scope bar: hierarchy chips (repo › workflow › run) on the left, dismissible filter chips on
// the right, and the shared branch/date scope (engineeringAnalyticsFiltersLogic) so a window picked on
// one page carries to the next.

import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { Fragment, ReactNode, useState } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonInput, LemonSelect, Link, Spinner } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { cn } from 'lib/utils/css-classes'
import { dateMapping } from 'lib/utils/dateFilters'
import { urls } from 'scenes/urls'

import { withScope } from '../lib/scope'
import { SHARED_DEFAULT_DATE_FROM, engineeringAnalyticsFiltersLogic } from '../scenes/engineeringAnalyticsFiltersLogic'
import { engineeringAnalyticsLogic } from '../scenes/engineeringAnalyticsLogic'
import { workflowSwitcherLogic } from '../scenes/workflowSwitcherLogic'

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
    /** Custom chip rendering (e.g. the workflow switcher); overrides `to`. `label` stays the key. */
    node?: ReactNode
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

/** Workflow crumb that doubles as a switcher: a searchable dropdown of the repo's workflows, loaded
 *  lazily on first open, navigating to the picked workflow's page. */
export function WorkflowScopeChip({
    repoOwner,
    repoName,
    workflowName,
    sourceId,
}: {
    repoOwner: string
    repoName: string
    workflowName: string
    sourceId: string | null
}): JSX.Element {
    const logic = workflowSwitcherLogic({ repoOwner, repoName, sourceId })
    const { workflowNames, workflowNamesLoading } = useValues(logic)
    const { ensureWorkflowsLoaded } = useActions(logic)
    const [visible, setVisible] = useState(false)
    const [search, setSearch] = useState('')

    const searchTerm = search.trim().toLowerCase()
    const options = (workflowNames ?? []).filter((name) => !searchTerm || name.toLowerCase().includes(searchTerm))

    const selectWorkflow = (name: string): void => {
        setVisible(false)
        setSearch('')
        if (name !== workflowName) {
            router.actions.push(
                withScope(
                    urls.engineeringAnalyticsWorkflowRuns(repoOwner, repoName, name),
                    router.values.currentLocation.searchParams,
                    sourceId
                )
            )
        }
    }

    return (
        <LemonDropdown
            visible={visible}
            onVisibilityChange={(next) => {
                setVisible(next)
                if (next) {
                    ensureWorkflowsLoaded()
                } else {
                    setSearch('')
                }
            }}
            closeOnClickInside={false}
            overlay={
                <div className="flex w-72 flex-col gap-1 p-1">
                    <LemonInput
                        type="search"
                        size="small"
                        placeholder="Search workflows…"
                        value={search}
                        onChange={setSearch}
                        autoFocus
                        data-attr="engineering-analytics-workflow-switcher-search"
                    />
                    <div className="max-h-80 overflow-y-auto">
                        {workflowNamesLoading ? (
                            <div className="flex items-center gap-2 px-2 py-1.5 text-xs text-secondary">
                                <Spinner /> Loading workflows…
                            </div>
                        ) : options.length > 0 ? (
                            options.map((name) => (
                                <LemonButton
                                    key={name}
                                    size="small"
                                    fullWidth
                                    active={name === workflowName}
                                    onClick={() => selectWorkflow(name)}
                                >
                                    <span className="truncate">{name}</span>
                                </LemonButton>
                            ))
                        ) : (
                            <div className="px-2 py-1.5 text-xs text-secondary">
                                {searchTerm ? 'No workflows match.' : 'No workflows in the window.'}
                            </div>
                        )}
                    </div>
                </div>
            }
        >
            <span
                className={cn(CHIP_CLASS, 'cursor-pointer')}
                title="Switch to another workflow in this repository"
                data-attr="engineering-analytics-workflow-switcher"
            >
                <strong className="font-semibold text-primary">{workflowName}</strong>
                <span className="text-[8px] text-tertiary">▼</span>
            </span>
        </LemonDropdown>
    )
}

/** Branch chip opening a small picker — a shared CI scope: an exact head_branch, all branches, or the
 *  pull-request lens (non-default-branch runs). Only workflow health honors the PR lens; exact-branch
 *  surfaces fall back to all branches for it. No default-branch preset — the repo's default (master vs
 *  main) isn't known here, so type it exactly instead of guessing. */
export function BranchScopeChip(): JSX.Element {
    const { branchInput, appliedBranch, pullRequestScope } = useValues(engineeringAnalyticsFiltersLogic)
    const { setBranchFilter, applyBranchFilter, setAppliedBranch, scopeToPullRequests } = useActions(
        engineeringAnalyticsFiltersLogic
    )
    const [visible, setVisible] = useState(false)

    return (
        <LemonDropdown
            visible={visible}
            onVisibilityChange={setVisible}
            closeOnClickInside={false}
            overlay={
                <div className="flex w-72 flex-col gap-2 p-1">
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
                        <LemonButton
                            size="xsmall"
                            type={pullRequestScope ? 'primary' : 'secondary'}
                            onClick={() => {
                                scopeToPullRequests()
                                setVisible(false)
                            }}
                            tooltip="CI on pull-request branches, excluding master/main. Same-repo PRs only — fork PRs carry no attribution. Applies to workflow health."
                        >
                            Pull requests
                        </LemonButton>
                        <LemonButton
                            size="xsmall"
                            type={!pullRequestScope && !appliedBranch ? 'primary' : 'secondary'}
                            onClick={() => {
                                setAppliedBranch('')
                                setVisible(false)
                            }}
                        >
                            all branches
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <span className={cn(CHIP_CLASS, 'cursor-pointer')} title="One CI scope for every section below">
                {pullRequestScope ? (
                    <strong className="font-semibold text-primary">pull requests</strong>
                ) : appliedBranch ? (
                    <>
                        {'branch: '}
                        <strong className="font-semibold text-primary">{appliedBranch}</strong>
                    </>
                ) : (
                    <strong className="font-semibold text-tertiary">all branches</strong>
                )}
                <span className="text-[8px] text-tertiary">▼</span>
            </span>
        </LemonDropdown>
    )
}

/** The shared window picker, wired to the cross-page date scope. Standalone so pages can place it outside
 *  the scope bar (the hub docks it in the repo header). */
export function ScopeDateFilter(): JSX.Element {
    const { dateFrom, dateTo } = useValues(engineeringAnalyticsFiltersLogic)
    const { setDateRange } = useActions(engineeringAnalyticsFiltersLogic)
    return (
        <DateFilter
            dateFrom={dateFrom}
            dateTo={dateTo}
            onChange={(from, to) => setDateRange(from ?? SHARED_DEFAULT_DATE_FROM, to ?? null)}
            dateOptions={SCOPE_DATE_OPTIONS}
            size="small"
        />
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
    return (
        <div className="flex flex-wrap items-center gap-2">
            {repoSlot}
            {crumbs.map((crumb) => (
                <Fragment key={crumb.label}>
                    <span className="text-xs text-tertiary">›</span>
                    {crumb.node ? (
                        crumb.node
                    ) : crumb.to ? (
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
                {showDate && <ScopeDateFilter />}
                {extra}
            </span>
        </div>
    )
}

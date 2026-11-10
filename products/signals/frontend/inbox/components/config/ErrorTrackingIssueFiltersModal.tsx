import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { QuickFilter } from '~/types'

import { AssigneeSelect } from 'products/error_tracking/frontend/components/IssueFilters/AssigneeSelect'
import { FilterGroup } from 'products/error_tracking/frontend/components/IssueFilters/FilterGroup'
import { issueFiltersLogic } from 'products/error_tracking/frontend/components/IssueFilters/issueFiltersLogic'
import { QuickFilterOptionSelect } from 'products/error_tracking/frontend/components/IssueFilters/QuickFilterOptionSelect'
import { SeveritySelect } from 'products/error_tracking/frontend/components/IssueFilters/SeveritySelect'

import {
    ErrorTrackingIssueFiltersModalLogicProps,
    INBOX_ISSUE_FILTERS_LOGIC_KEY,
    ISSUE_FILTERS_QUICK_FILTER_CONTEXT,
    errorTrackingIssueFiltersModalLogic,
} from '../../logics/errorTrackingIssueFiltersModalLogic'

// Only what the server filter can evaluate: no person properties, cohorts, or HogQL.
const ISSUE_FILTER_GROUP_TYPES = [
    TaxonomicFilterGroupType.ErrorTrackingProperties,
    TaxonomicFilterGroupType.ErrorTrackingIssues,
    TaxonomicFilterGroupType.EventProperties,
]

export function ErrorTrackingIssueFiltersModal(props: ErrorTrackingIssueFiltersModalLogicProps): JSX.Element {
    const logic = errorTrackingIssueFiltersModalLogic(props)
    const { severity, assignee, saving, saveDisabledReason, storedFilterCount, quickFilters, quickFilterSelections } =
        useValues(logic)
    const { setSeverity, setAssignee, pickQuickFilter, saveFilters, clearFilters } = useActions(logic)

    const handleClose = (): void => {
        if (!saving) {
            props.onClose()
        }
    }

    return (
        <LemonModal
            isOpen
            onClose={handleClose}
            title="Error tracking filters"
            description="Choose which error tracking issues can reach your inbox. Issues that don't match are skipped before any AI work starts. With no filters, every issue can."
            width={640}
            footer={
                <div className="flex w-full flex-wrap items-center justify-between gap-2">
                    {storedFilterCount > 0 ? (
                        <LemonButton
                            type="secondary"
                            status="danger"
                            onClick={clearFilters}
                            disabledReason={saving ? 'Saving' : undefined}
                            data-attr="signal-source-issue-filters-clear"
                        >
                            Clear filters
                        </LemonButton>
                    ) : (
                        <span />
                    )}
                    <div className="flex flex-wrap items-center gap-2">
                        <LemonButton
                            type="secondary"
                            onClick={handleClose}
                            disabledReason={saving ? 'Saving' : undefined}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={saveFilters}
                            loading={saving}
                            disabledReason={saving ? undefined : (saveDisabledReason ?? undefined)}
                            data-attr="signal-source-issue-filters-save"
                        >
                            Save
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div className="flex flex-col gap-4">
                <BindLogic logic={issueFiltersLogic} props={{ logicKey: INBOX_ISSUE_FILTERS_LOGIC_KEY }}>
                    <div className="flex flex-wrap items-center gap-2" data-attr="signal-source-issue-filters-controls">
                        <SeveritySelect severity={severity} onChange={setSeverity} />
                        <AssigneeSelect assignee={assignee} onChange={setAssignee} />
                        {quickFilters.map((filter: QuickFilter) => (
                            <QuickFilterOptionSelect
                                key={filter.id}
                                filter={filter}
                                context={ISSUE_FILTERS_QUICK_FILTER_CONTEXT}
                                selectedOptionId={quickFilterSelections[filter.id] ?? null}
                                onChange={(option) => pickQuickFilter(filter, option)}
                            />
                        ))}
                        <FilterGroup
                            rootKey={INBOX_ISSUE_FILTERS_LOGIC_KEY}
                            taxonomicGroupTypes={ISSUE_FILTER_GROUP_TYPES}
                        />
                    </div>
                </BindLogic>
                <ul className="m-0 flex list-disc flex-col gap-1 pl-4 text-xs text-secondary">
                    <li>
                        Filters check one exception per issue: the first one for a new issue, the one that reopened it,
                        or an example from a spike. An issue first seen on staging won't match an environment filter for
                        production until it reopens or spikes there.
                    </li>
                    <li>An issue with no severity doesn't match a severity filter.</li>
                    <li>
                        When the exception isn't available, a filter on an exception property skips the issue. This
                        happens for existing issues added when you turn the source on.
                    </li>
                    <li>
                        Filters apply to new signals only. They decide which issues are eligible, and they are not a
                        spend limit.
                    </li>
                </ul>
            </div>
        </LemonModal>
    )
}

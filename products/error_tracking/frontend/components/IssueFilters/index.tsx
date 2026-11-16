import { AssigneeFilter } from './Assignee'
import { DateRangeFilter } from './DateRange'
import { FilterGroup } from './FilterGroup'
import { InternalAccountsFilter } from './InternalAccounts'
import { IssueTagFilter } from './IssueTagFilter'
import { ErrorFiltersRoot } from './Root'
import { IssueSearchInput } from './Search'
import { SeverityFilter } from './Severity'
import { StatusFilter } from './Status'

export const ErrorFilters = {
    Root: ErrorFiltersRoot,
    DateRange: DateRangeFilter,
    FilterGroup: FilterGroup,
    Assignee: AssigneeFilter,
    Status: StatusFilter,
    Severity: SeverityFilter,
    IssueTag: IssueTagFilter,
    InternalAccounts: InternalAccountsFilter,
    Search: IssueSearchInput,
}

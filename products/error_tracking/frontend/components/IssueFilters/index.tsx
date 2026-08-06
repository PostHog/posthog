import { AssigneeFilter } from '../Assignee/ErrorTrackingAssigneeSelectButton'
import { DateRangeFilter } from './DateRange'
import { FilterGroup } from './FilterGroup'
import { InternalAccountsFilter } from './InternalAccounts'
import { ErrorFiltersRoot } from './Root'
import { IssueSearchInput } from './Search'
import { StatusFilter } from './Status'

export const ErrorFilters = {
    Root: ErrorFiltersRoot,
    DateRange: DateRangeFilter,
    FilterGroup: FilterGroup,
    Assignee: AssigneeFilter,
    Status: StatusFilter,
    InternalAccounts: InternalAccountsFilter,
    Search: IssueSearchInput,
}

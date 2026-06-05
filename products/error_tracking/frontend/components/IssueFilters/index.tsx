import { AssigneeFilter } from '../Assignee/ErrorTrackingAssigneeSelectButton'
import { DateRangeFilter } from './DateRange'
import { StatusFilter } from './ErrorTrackingStatusSelect'
import { FilterGroup } from './FilterGroup'
import { InternalAccountsFilter } from './InternalAccounts'
import { ErrorFiltersRoot } from './Root'

export const ErrorFilters = {
    Root: ErrorFiltersRoot,
    DateRange: DateRangeFilter,
    FilterGroup: FilterGroup,
    Assignee: AssigneeFilter,
    Status: StatusFilter,
    InternalAccounts: InternalAccountsFilter,
}

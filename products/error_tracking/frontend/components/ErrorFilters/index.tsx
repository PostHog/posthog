import { DateRangeFilter } from './DateRange'
import { FilterGroup } from './FilterGroup'
import { InternalAccountsFilter } from './InternalAccounts'
import { ErrorFiltersRoot } from './Root'

export const ErrorFilters = {
    Root: ErrorFiltersRoot,
    DateRange: DateRangeFilter,
    FilterGroup: FilterGroup,
    InternalAccounts: InternalAccountsFilter,
}

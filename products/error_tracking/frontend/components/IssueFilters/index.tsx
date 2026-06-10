import { AssigneeFilter } from '../Assignee/ErrorTrackingAssigneeSelectButton'
import { DateRangeFilter } from './DateRange'
import { FilterGroup } from './FilterGroup'
import { FilterSettingsMenu } from './InternalAccounts'
import { ErrorFiltersRoot } from './Root'
import { SearchBar, SearchBarDivider } from './SearchBar'
import { StatusFilter } from './Status'

export const ErrorFilters = {
    Root: ErrorFiltersRoot,
    DateRange: DateRangeFilter,
    FilterGroup: FilterGroup,
    Assignee: AssigneeFilter,
    Status: StatusFilter,
    SettingsMenu: FilterSettingsMenu,
    SearchBar: SearchBar,
    SearchBarDivider: SearchBarDivider,
}

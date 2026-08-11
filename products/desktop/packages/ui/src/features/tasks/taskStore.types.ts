import type {
  ActiveFilters,
  FilterCategory,
  FilterMatchMode,
  FilterOperator,
  GroupByField,
  OrderByField,
  OrderDirection,
} from "@posthog/core/tasks/filters";

export type {
  ActiveFilters,
  FilterCategory,
  FilterMatchMode,
  FilterOperator,
  FilterValue,
  GroupByField,
  OrderByField,
  OrderDirection,
} from "@posthog/core/tasks/filters";
export { TASK_STATUS_ORDER } from "@posthog/core/tasks/filters";

export interface TaskState {
  selectedIndex: number | null;
  hoveredIndex: number | null;
  contextMenuIndex: number | null;
  filter: string;
  orderBy: OrderByField;
  orderDirection: OrderDirection;
  groupBy: GroupByField;
  expandedGroups: Record<string, boolean>;
  activeFilters: ActiveFilters;
  filterMatchMode: FilterMatchMode;
  filterSearchQuery: string;
  filterMenuSelectedIndex: number;
  isFilterDropdownOpen: boolean;
  editingFilterBadgeKey: string | null;

  setSelectedIndex: (index: number | null) => void;
  setHoveredIndex: (index: number | null) => void;
  setContextMenuIndex: (index: number | null) => void;
  setFilter: (filter: string) => void;
  setOrderBy: (orderBy: OrderByField) => void;
  setOrderDirection: (orderDirection: OrderDirection) => void;
  setGroupBy: (groupBy: GroupByField) => void;
  toggleGroupExpanded: (groupName: string) => void;
  setActiveFilters: (filters: ActiveFilters) => void;
  clearActiveFilters: () => void;
  toggleFilter: (
    category: FilterCategory,
    value: string,
    operator?: FilterOperator,
  ) => void;
  addFilter: (
    category: FilterCategory,
    value: string,
    operator?: FilterOperator,
  ) => void;
  updateFilter: (
    category: FilterCategory,
    oldValue: string,
    newValue: string,
  ) => void;
  toggleFilterOperator: (category: FilterCategory, value: string) => void;
  setFilterMatchMode: (mode: FilterMatchMode) => void;
  setFilterSearchQuery: (query: string) => void;
  setFilterMenuSelectedIndex: (index: number) => void;
  setIsFilterDropdownOpen: (open: boolean) => void;
  setEditingFilterBadgeKey: (key: string | null) => void;
}

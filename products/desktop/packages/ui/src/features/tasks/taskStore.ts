import * as filters from "@posthog/core/tasks/filters";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { TaskState } from "./taskStore.types";

export const useTaskStore = create<TaskState>()(
  persist(
    (set) => ({
      selectedIndex: null,
      hoveredIndex: null,
      contextMenuIndex: null,
      filter: "",
      orderBy: "created_at",
      orderDirection: "desc",
      groupBy: "none",
      expandedGroups: {},
      activeFilters: {},
      filterMatchMode: "all",
      filterSearchQuery: "",
      filterMenuSelectedIndex: -1,
      isFilterDropdownOpen: false,
      editingFilterBadgeKey: null,

      setSelectedIndex: (index) => set({ selectedIndex: index }),
      setHoveredIndex: (index) => set({ hoveredIndex: index }),
      setContextMenuIndex: (index) => set({ contextMenuIndex: index }),

      setFilter: (filter) => set({ filter }),
      setOrderBy: (orderBy) => set({ orderBy }),
      setOrderDirection: (orderDirection) => set({ orderDirection }),
      setGroupBy: (groupBy) => set({ groupBy }),

      toggleGroupExpanded: (groupName) =>
        set((state) => ({
          expandedGroups: {
            ...state.expandedGroups,
            [groupName]: !(state.expandedGroups[groupName] ?? true),
          },
        })),

      setActiveFilters: (activeFilters) => set({ activeFilters }),
      clearActiveFilters: () => set({ activeFilters: {} }),

      toggleFilter: (category, value, operator) =>
        set((state) => ({
          activeFilters: filters.toggleFilter(
            state.activeFilters,
            category,
            value,
            operator,
          ),
        })),

      addFilter: (category, value, operator) =>
        set((state) => ({
          activeFilters: filters.addFilter(
            state.activeFilters,
            category,
            value,
            operator,
          ),
        })),

      updateFilter: (category, oldValue, newValue) =>
        set((state) => ({
          activeFilters: filters.updateFilter(
            state.activeFilters,
            category,
            oldValue,
            newValue,
          ),
        })),

      toggleFilterOperator: (category, value) =>
        set((state) => ({
          activeFilters: filters.toggleFilterOperator(
            state.activeFilters,
            category,
            value,
          ),
        })),

      setFilterMatchMode: (mode) => set({ filterMatchMode: mode }),
      setFilterSearchQuery: (query) => set({ filterSearchQuery: query }),
      setFilterMenuSelectedIndex: (index) =>
        set({ filterMenuSelectedIndex: index }),
      setIsFilterDropdownOpen: (open) => set({ isFilterDropdownOpen: open }),
      setEditingFilterBadgeKey: (key) => set({ editingFilterBadgeKey: key }),
    }),
    {
      name: "task-store",
      partialize: (state) => ({
        orderBy: state.orderBy,
        orderDirection: state.orderDirection,
        groupBy: state.groupBy,
        expandedGroups: state.expandedGroups,
        activeFilters: state.activeFilters,
        filterMatchMode: state.filterMatchMode,
      }),
    },
  ),
);

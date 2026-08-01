import { ALL_WORKSPACE_MODES } from "@posthog/core/sidebar/buildSidebarData";
import type { WorkspaceMode } from "@posthog/shared";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import {
  type CustomizableNavItemId,
  type NavItemOverrides,
  SIDEBAR_MIN_WIDTH,
  sanitizeNavItemOrder,
  sanitizeNavItemOverrides,
} from "./constants";

interface SidebarStoreState {
  open: boolean;
  hasUserSetOpen: boolean;
  width: number;
  isResizing: boolean;
  collapsedSections: Set<string>;
  folderOrder: string[];
  historyVisibleCount: number;
  organizeMode: "by-project" | "chronological";
  sortMode: "updated" | "created";
  showAllUsers: boolean;
  showInternal: boolean;
  taskTypeFilter: WorkspaceMode[];
  // Reveals the Channels feature in the unified sidebar (channel tree replaces
  // the task list, Canvas nav item appears). Off by default — Code merged into
  // the Bluebird chrome ships with channels hidden until the user opts in.
  channelsEnabled: boolean;
  // Per-item visibility overrides from the Customize sidebar dialog. Items
  // absent from the map follow their CUSTOMIZABLE_NAV_ITEMS defaultVisible, so newly
  // shipped moreable items keep their intended default for existing users.
  navItemOverrides: NavItemOverrides;
  // Drag order from the Customize sidebar dialog. Empty means default order;
  // ids absent from it (newly shipped items) render after the ordered ones.
  navItemOrder: readonly CustomizableNavItemId[];
}

interface SidebarStoreActions {
  setOpen: (open: boolean) => void;
  setOpenAuto: (open: boolean) => void;
  toggle: () => void;
  setWidth: (width: number) => void;
  setIsResizing: (isResizing: boolean) => void;
  toggleSection: (sectionId: string) => void;
  reorderFolders: (fromIndex: number, toIndex: number) => void;
  setFolderOrder: (order: string[]) => void;
  syncFolderOrder: (folderIds: string[]) => void;
  loadMoreHistory: () => void;
  resetHistoryVisibleCount: () => void;
  setOrganizeMode: (mode: SidebarStoreState["organizeMode"]) => void;
  setSortMode: (mode: SidebarStoreState["sortMode"]) => void;
  setShowAllUsers: (showAllUsers: boolean) => void;
  setShowInternal: (showInternal: boolean) => void;
  toggleTaskType: (mode: WorkspaceMode) => void;
  setChannelsEnabled: (channelsEnabled: boolean) => void;
  setNavItemVisible: (item: CustomizableNavItemId, visible: boolean) => void;
  setNavItemOrder: (order: readonly CustomizableNavItemId[]) => void;
}

type SidebarStore = SidebarStoreState & SidebarStoreActions;

export const useSidebarStore = create<SidebarStore>()(
  persist(
    (set) => ({
      open: false,
      hasUserSetOpen: false,
      width: 256,
      isResizing: false,
      collapsedSections: new Set<string>(),
      folderOrder: [],
      historyVisibleCount: 25,
      organizeMode: "by-project",
      sortMode: "updated",
      showAllUsers: false,
      showInternal: false,
      taskTypeFilter: [...ALL_WORKSPACE_MODES],
      channelsEnabled: false,
      navItemOverrides: {},
      navItemOrder: [],
      setOpen: (open) => set({ open, hasUserSetOpen: true }),
      setOpenAuto: (open) =>
        set((state) => (state.hasUserSetOpen ? state : { open })),
      toggle: () =>
        set((state) => ({ open: !state.open, hasUserSetOpen: true })),
      setWidth: (width) => set({ width }),
      setIsResizing: (isResizing) => set({ isResizing }),
      toggleSection: (sectionId) =>
        set((state) => {
          const newCollapsedSections = new Set(state.collapsedSections);
          if (newCollapsedSections.has(sectionId)) {
            newCollapsedSections.delete(sectionId);
          } else {
            newCollapsedSections.add(sectionId);
          }
          return { collapsedSections: newCollapsedSections };
        }),
      reorderFolders: (fromIndex, toIndex) =>
        set((state) => {
          const newOrder = [...state.folderOrder];
          const [removed] = newOrder.splice(fromIndex, 1);
          newOrder.splice(toIndex, 0, removed);
          return { folderOrder: newOrder };
        }),
      setFolderOrder: (order) => set({ folderOrder: order }),
      syncFolderOrder: (folderIds) =>
        set((state) => {
          const existingOrder = state.folderOrder.filter((id) =>
            folderIds.includes(id),
          );
          const newFolders = folderIds.filter(
            (id) => !state.folderOrder.includes(id),
          );
          if (
            newFolders.length > 0 ||
            existingOrder.length !== state.folderOrder.length
          ) {
            return { folderOrder: [...existingOrder, ...newFolders] };
          }
          return state;
        }),
      loadMoreHistory: () =>
        set((state) => ({
          historyVisibleCount: state.historyVisibleCount + 25,
        })),
      resetHistoryVisibleCount: () => set({ historyVisibleCount: 25 }),
      setOrganizeMode: (organizeMode) => set({ organizeMode }),
      setSortMode: (sortMode) => set({ sortMode }),
      setShowAllUsers: (showAllUsers) => set({ showAllUsers }),
      setShowInternal: (showInternal) => set({ showInternal }),
      toggleTaskType: (mode) =>
        set((state) => ({
          taskTypeFilter: state.taskTypeFilter.includes(mode)
            ? state.taskTypeFilter.filter((m) => m !== mode)
            : [...state.taskTypeFilter, mode],
        })),
      setChannelsEnabled: (channelsEnabled) => set({ channelsEnabled }),
      setNavItemVisible: (item, visible) =>
        set((state) => ({
          navItemOverrides: { ...state.navItemOverrides, [item]: visible },
        })),
      setNavItemOrder: (navItemOrder) => set({ navItemOrder }),
    }),
    {
      name: "sidebar-storage",
      partialize: (state) => ({
        open: state.open,
        hasUserSetOpen: state.hasUserSetOpen,
        width: state.width,
        collapsedSections: Array.from(state.collapsedSections),
        folderOrder: state.folderOrder,
        historyVisibleCount: state.historyVisibleCount,
        organizeMode: state.organizeMode,
        sortMode: state.sortMode,
        showAllUsers: state.showAllUsers,
        showInternal: state.showInternal,
        taskTypeFilter: state.taskTypeFilter,
        channelsEnabled: state.channelsEnabled,
        navItemOverrides: state.navItemOverrides,
        navItemOrder: state.navItemOrder,
      }),
      merge: (persisted, current) => {
        const persistedState = persisted as {
          open?: boolean;
          hasUserSetOpen?: boolean;
          width?: number;
          collapsedSections?: string[];
          folderOrder?: string[];
          historyVisibleCount?: number;
          organizeMode?: SidebarStoreState["organizeMode"];
          sortMode?: SidebarStoreState["sortMode"];
          showAllUsers?: boolean;
          showInternal?: boolean;
          taskTypeFilter?: WorkspaceMode[];
          channelsEnabled?: boolean;
          navItemOverrides?: unknown;
          navItemOrder?: unknown;
        };
        return {
          ...current,
          open: persistedState.open ?? current.open,
          hasUserSetOpen:
            persistedState.hasUserSetOpen ?? current.hasUserSetOpen,
          width: Math.max(
            SIDEBAR_MIN_WIDTH,
            persistedState.width ?? current.width,
          ),
          collapsedSections: new Set(persistedState.collapsedSections ?? []),
          folderOrder: persistedState.folderOrder ?? [],
          historyVisibleCount:
            persistedState.historyVisibleCount ?? current.historyVisibleCount,
          organizeMode: persistedState.organizeMode ?? current.organizeMode,
          sortMode: persistedState.sortMode ?? current.sortMode,
          showAllUsers: persistedState.showAllUsers ?? current.showAllUsers,
          showInternal: persistedState.showInternal ?? current.showInternal,
          taskTypeFilter:
            persistedState.taskTypeFilter ?? current.taskTypeFilter,
          channelsEnabled:
            persistedState.channelsEnabled ?? current.channelsEnabled,
          navItemOverrides: sanitizeNavItemOverrides(
            persistedState.navItemOverrides,
          ),
          navItemOrder: sanitizeNavItemOrder(persistedState.navItemOrder),
        };
      },
    },
  ),
);

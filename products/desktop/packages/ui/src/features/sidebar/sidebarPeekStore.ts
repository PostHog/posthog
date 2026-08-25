import { create } from "zustand";

// Ephemeral hover-peek state for the collapsed sidebar: hovering the left
// gutter or the title-bar toggle slides the sidebar out as an overlay, and
// leaving hides it. Re-entering any trigger before the hide fires keeps the
// peek alive. A "hold" keeps it open regardless of pointer position while a
// menu spawned from the sidebar (e.g. the ProjectSwitcher dropdown) is open, so
// moving the pointer toward the menu can't slide the anchor away. Not persisted.
interface SidebarPeekStore {
  peek: boolean;
  setPeek: (peek: boolean) => void;
}

export const useSidebarPeekStore = create<SidebarPeekStore>()((set) => ({
  peek: false,
  setPeek: (peek) => set({ peek }),
}));

// The hide timer is shared across every trigger (gutter, toggle button, the
// panel itself) so re-entering any of them keeps the peek alive.
let hideTimer: ReturnType<typeof setTimeout> | null = null;

// While a sidebar-spawned menu is open the peek is "held": endSidebarPeek is a
// no-op so a pointer that leaves the panel (e.g. toward a submenu flyout) can't
// collapse it and strand the open menu's portal anchor. Counted, not boolean,
// so one menu's release can't drop a hold another menu still needs.
let holdCount = 0;

const clearHideTimer = (): void => {
  if (hideTimer) {
    clearTimeout(hideTimer);
    hideTimer = null;
  }
};

export function beginSidebarPeek(): void {
  clearHideTimer();
  useSidebarPeekStore.getState().setPeek(true);
}

// Pin the peek open while a menu spawned from the sidebar is open, and release
// it when that menu closes. Paired open/close calls keep this balanced;
// releasing hands control back to the hover logic, which collapses the peek on
// the next pointer move outside the panel.
export function holdSidebarPeek(): void {
  holdCount += 1;
  clearHideTimer();
}

export function releaseSidebarPeek(): void {
  holdCount = Math.max(0, holdCount - 1);
}

export function endSidebarPeek(delayMs = 0): void {
  if (holdCount > 0) return;
  clearHideTimer();
  hideTimer = setTimeout(() => {
    hideTimer = null;
    useSidebarPeekStore.getState().setPeek(false);
  }, delayMs);
}

export function cancelSidebarPeek(): void {
  holdCount = 0;
  clearHideTimer();
  useSidebarPeekStore.getState().setPeek(false);
}

import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ThemePreference = "light" | "dark" | "system";

interface ThemeStoreState {
  theme: ThemePreference;
  isDarkMode: boolean;
}

interface ThemeStoreActions {
  setTheme: (theme: ThemePreference) => void;
  cycleTheme: () => void;
}

type ThemeStore = ThemeStoreState & ThemeStoreActions;

const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");

export function resolveIsDarkMode(theme: ThemePreference): boolean {
  if (theme === "system") {
    return mediaQuery.matches;
  }
  return theme === "dark";
}

const THEME_CYCLE: ThemePreference[] = ["dark", "light", "system"];

export const THEME_CYCLE_LABELS: Record<ThemePreference, string> = {
  dark: "Switch to light mode",
  light: "Switch to system theme",
  system: "Switch to dark mode",
};

export const useThemeStore = create<ThemeStore>()(
  persist(
    (set) => ({
      theme: "system",
      isDarkMode: mediaQuery.matches,
      setTheme: (theme) => set({ theme, isDarkMode: resolveIsDarkMode(theme) }),
      cycleTheme: () =>
        set((state) => {
          const nextIndex =
            (THEME_CYCLE.indexOf(state.theme) + 1) % THEME_CYCLE.length;
          const next = THEME_CYCLE[nextIndex];
          return { theme: next, isDarkMode: resolveIsDarkMode(next) };
        }),
    }),
    {
      name: "theme-storage",
      version: 1,
      migrate: (persistedState: unknown, version: number) => {
        const state = persistedState as Record<string, unknown>;
        if (version === 0) {
          const wasDark = state.isDarkMode !== false;
          return {
            ...state,
            theme: wasDark ? "dark" : "light",
            isDarkMode: wasDark,
          };
        }
        return state as unknown as ThemeStore;
      },
      merge: (persistedState, currentState) => {
        const merged = {
          ...currentState,
          ...(persistedState as Partial<ThemeStore>),
        };
        merged.isDarkMode = resolveIsDarkMode(merged.theme);
        return merged;
      },
      partialize: (state) => ({ theme: state.theme }) as unknown as ThemeStore,
    },
  ),
);

mediaQuery.addEventListener("change", () => {
  const { theme } = useThemeStore.getState();
  if (theme === "system") {
    useThemeStore.setState({ isDarkMode: mediaQuery.matches });
  }
});

// Sync the .dark class on <html> so CSS that uses .dark selector (e.g. quill
// color tokens) switches correctly. Radix Themes uses its own `appearance` prop
// and doesn't toggle this class.
function syncDarkClass(isDarkMode: boolean) {
  document.documentElement.classList.toggle("dark", isDarkMode);
}

syncDarkClass(useThemeStore.getState().isDarkMode);
useThemeStore.subscribe((state) => syncDarkClass(state.isDarkMode));

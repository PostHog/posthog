import {
  DEFAULT_NAV_RAIL_SIZE,
  type NavRailSize,
  useSettingsStore,
} from "@posthog/ui/features/settings/settingsStore";

export interface NavRailMetrics {
  /** Sits outside the sidebar, so anything measuring from the window's left
   *  edge has to add it. */
  width: number;
  iconSize: number;
  tileClassName: string;
  captionClassName: string | null;
  gapClassName: string;
}

// Full class strings, so Tailwind's scanner sees every one of them.
export const NAV_RAIL_METRICS: Readonly<Record<NavRailSize, NavRailMetrics>> = {
  small: {
    width: 44,
    iconSize: 16,
    tileClassName: "size-8",
    captionClassName: null,
    gapClassName: "gap-1.5",
  },
  medium: {
    width: 54,
    iconSize: 18,
    tileClassName: "size-7",
    captionClassName: "font-bold text-[7px] leading-2",
    gapClassName: "gap-2",
  },
  large: {
    width: 64,
    iconSize: 20,
    tileClassName: "size-9",
    captionClassName: "font-medium text-[9px] leading-2",
    gapClassName: "gap-2",
  },
};

export function useNavRailMetrics(): NavRailMetrics {
  const size = useSettingsStore((state) => state.navRailSize);
  // A persisted value from a build with different sizes falls back.
  return NAV_RAIL_METRICS[size] ?? NAV_RAIL_METRICS[DEFAULT_NAV_RAIL_SIZE];
}

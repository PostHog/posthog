import type { Icon } from "@phosphor-icons/react";
import {
  Bug,
  ChartLine,
  Copy,
  Flag,
  Flask,
  Funnel,
  Lightning,
  Lock,
  Sparkle,
  Trash,
  Warning,
  Wrench,
} from "@phosphor-icons/react";
import type { DiscoveredTask } from "@posthog/core/setup/types";

export interface CategoryConfig {
  icon: Icon;
  color: string;
  label: string;
}

// Single source of truth for how each `DiscoveredTask` category renders.
// Consumers (suggestion cards, detail pane, etc.) read from here so that
// adding a category to `DiscoveredTask` only requires updating one map.
export const CATEGORY_CONFIG: Record<
  DiscoveredTask["category"],
  CategoryConfig
> = {
  bug: { icon: Bug, color: "red", label: "Bug" },
  security: { icon: Lock, color: "red", label: "Security" },
  dead_code: { icon: Trash, color: "gray", label: "Dead code" },
  duplication: { icon: Copy, color: "orange", label: "Duplication" },
  performance: { icon: Lightning, color: "green", label: "Performance" },
  stale_feature_flag: { icon: Flag, color: "amber", label: "Stale flag" },
  error_tracking: { icon: Warning, color: "orange", label: "Error tracking" },
  event_tracking: { icon: ChartLine, color: "blue", label: "Event tracking" },
  funnel: { icon: Funnel, color: "violet", label: "Funnel" },
  posthog_setup: { icon: Sparkle, color: "violet", label: "PostHog setup" },
  experiment: { icon: Flask, color: "purple", label: "Experiment" },
};

// Fallback when a `DiscoveredTask.category` somehow doesn't match the map
// (e.g. an agent emits a value the schema didn't constrain).
export const FALLBACK_CATEGORY_CONFIG: CategoryConfig = {
  icon: Wrench,
  color: "gray",
  label: "Suggestion",
};

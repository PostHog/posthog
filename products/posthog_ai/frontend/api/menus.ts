// Menu items for hosts that render a task's actions in their own menu, such as the PostHog AI panel.
//
// Part of the `products/posthog_ai/frontend/api/<module>` public surface. Kept apart from ./primitives, which pulls the
// thread and its tool widgets, because the panel's menu loads with the app shell.

// A task's overflow menu items: placement, actions and details. Shared by the task page and the PostHog AI panel.
export { TaskMenuItems } from '../scenes/TaskTracker/components/TaskMenuItems'
export type { TaskMenuItemsProps } from '../scenes/TaskTracker/components/TaskMenuItems'

// The staff debug logs switch, drawn with a host's menu parts.
export { DebugLogsMenuItem } from '../components/DebugLogsMenuItem'

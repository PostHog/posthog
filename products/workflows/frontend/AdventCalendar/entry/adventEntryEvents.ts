import posthog from 'posthog-js'

import type { CategorySuffixNav } from '~/layout/panel-layout/ProjectTree/customCategorySuffixRegistry'

// pinned: analytics event name, renaming it breaks the entry point dashboards
const ENTRY_CLICKED = 'workflows advent entry clicked'

export function reportAdventEntryClicked(entry: 'card' | 'nav-tree', nav?: CategorySuffixNav): void {
    posthog.capture(ENTRY_CLICKED, { entry, nav })
}

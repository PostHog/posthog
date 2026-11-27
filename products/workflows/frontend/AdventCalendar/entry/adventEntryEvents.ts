import posthog from 'posthog-js'
import type { MouseEvent } from 'react'

import type { CategorySuffixNav } from '~/layout/panel-layout/ProjectTree/CustomCategorySuffix'

import { adventHasWorkflows } from '../adventHasWorkflows'

const MIDDLE_BUTTON = 1

const PINNED_ENTRY_CLICKED_EVENT = 'workflows advent entry clicked'

export function reportAdventEntryClicked(entry: 'card' | 'nav-tree', nav?: CategorySuffixNav): void {
    posthog.capture(PINNED_ENTRY_CLICKED_EVENT, { entry, nav, has_workflows: adventHasWorkflows() })
}

export function reportAdventEntryMiddleClicked(
    event: MouseEvent<HTMLElement>,
    entry: 'card' | 'nav-tree',
    nav?: CategorySuffixNav
): void {
    if (event.button === MIDDLE_BUTTON) {
        reportAdventEntryClicked(entry, nav)
    }
}

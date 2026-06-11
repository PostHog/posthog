import { ErrorFilters } from 'products/error_tracking/frontend/components/IssueFilters'

import { ERROR_TRACKING_SCENE_LOGIC_KEY } from '../../../errorTrackingSceneLogic'
import { ListReloadButton } from '../IssuesList'
import { OmniBar, QUICK_FILTER_CONTEXT } from './OmniBar'
import { CombinedSortButton } from './SortButtons'

const ClusterSeparator = (): JSX.Element => <div className="w-px h-5 bg-border shrink-0" />

/**
 * Variant E — "Pure bar + control cluster".
 * The omnibar holds nothing but the query: search, chips, and the `/` hint.
 * Every secondary control lives in a detached pill-shaped cluster on the
 * right — the hero bar stays perfectly calm, and view controls have their
 * own clearly-bounded home.
 */
export function IssuesFiltersE(): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <div className="flex-1 min-w-0">
                <OmniBar />
            </div>
            <div className="flex items-center h-11 px-1 gap-0.5 rounded-full border bg-[var(--color-bg-fill-input)] shadow-sm shrink-0">
                <ListReloadButton />
                <ClusterSeparator />
                <ErrorFilters.DateRange size="small" type="tertiary" />
                <ClusterSeparator />
                <CombinedSortButton />
                <ClusterSeparator />
                <ErrorFilters.SettingsMenu
                    quickFilterContext={QUICK_FILTER_CONTEXT}
                    logicKey={ERROR_TRACKING_SCENE_LOGIC_KEY}
                />
            </div>
        </div>
    )
}

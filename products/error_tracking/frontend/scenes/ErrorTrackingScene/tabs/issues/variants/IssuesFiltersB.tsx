import { ErrorFilters } from 'products/error_tracking/frontend/components/IssueFilters'

import { ERROR_TRACKING_SCENE_LOGIC_KEY } from '../../../errorTrackingSceneLogic'
import { ListReloadButton } from '../IssuesList'
import { OmniBar, QUICK_FILTER_CONTEXT } from './OmniBar'
import { CombinedSortButton } from './SortButtons'

/**
 * Variant B — "Hero omnibar".
 * The original omnibar: chips and search share the focal input, all secondary
 * controls sit inside the bar's right edge at a uniform size.
 */
export function IssuesFiltersB(): JSX.Element {
    return (
        <OmniBar
            trailing={
                <>
                    <ErrorFilters.DateRange size="small" type="tertiary" />
                    <CombinedSortButton />
                    <ErrorFilters.SettingsMenu
                        quickFilterContext={QUICK_FILTER_CONTEXT}
                        logicKey={ERROR_TRACKING_SCENE_LOGIC_KEY}
                    />
                    <ListReloadButton />
                </>
            }
        />
    )
}

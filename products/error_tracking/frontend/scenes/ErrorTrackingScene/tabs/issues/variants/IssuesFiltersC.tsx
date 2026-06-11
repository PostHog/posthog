import { ErrorFilters } from 'products/error_tracking/frontend/components/IssueFilters'

import { ERROR_TRACKING_SCENE_LOGIC_KEY } from '../../../errorTrackingSceneLogic'
import { ListReloadButton } from '../IssuesList'
import { OmniBar, QUICK_FILTER_CONTEXT } from './OmniBar'
import { SortDirectionButton, SortFieldButton } from './SortButtons'

/**
 * Variant C — "Scope first".
 * Reading order matches the mental model: time scope on the left edge (like a
 * browser address bar's site chip), the query in the middle, arrangement on the
 * right — with sort field and direction split into two one-click buttons.
 */
export function IssuesFiltersC(): JSX.Element {
    return (
        <OmniBar
            leading={<ErrorFilters.DateRange size="small" type="tertiary" />}
            trailing={
                <>
                    <SortFieldButton />
                    <SortDirectionButton />
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

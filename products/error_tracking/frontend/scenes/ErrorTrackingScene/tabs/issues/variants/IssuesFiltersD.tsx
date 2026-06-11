import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'

import { ErrorFilters } from 'products/error_tracking/frontend/components/IssueFilters'
import { TAXONOMIC_GROUP_TYPES } from 'products/error_tracking/frontend/components/IssueFilters/consts'
import {
    InternalUsersChip,
    IssueFilterChips,
    QuickFilterChips,
    UniversalFilterGroup,
} from 'products/error_tracking/frontend/components/IssueFilters/FilterGroup'

import { ERROR_TRACKING_SCENE_LOGIC_KEY } from '../../../errorTrackingSceneLogic'
import { ListReloadButton } from '../IssuesList'
import { OmniBar, OmniBarSeparator, QUICK_FILTER_CONTEXT } from './OmniBar'
import { SortDirectionButton, SortFieldButton } from './SortButtons'

/**
 * Variant D — "Two-story command deck".
 * The top story is a pure search field; the bottom story (inside the same
 * frame) is a filter rail holding every chip and scope control. The whole
 * instrument reads as one surface, but typing and filtering never compete
 * for the same pixels.
 */
export function IssuesFiltersD(): JSX.Element {
    return (
        <OmniBar
            placeholder="Search issues..."
            showIssueChips={false}
            showContextChips={false}
            showFilterChips={false}
            trailing={<ListReloadButton />}
            secondRow={
                <>
                    <UniversalFilters.AddFilterButton size="small" type="secondary" />
                    <IssueFilterChips />
                    <InternalUsersChip />
                    <QuickFilterChips context={QUICK_FILTER_CONTEXT} logicKey={ERROR_TRACKING_SCENE_LOGIC_KEY} />
                    <UniversalFilterGroup taxonomicGroupTypes={TAXONOMIC_GROUP_TYPES} />
                    <div className="flex-1" />
                    <ErrorFilters.DateRange size="small" type="tertiary" />
                    <OmniBarSeparator />
                    <SortFieldButton />
                    <SortDirectionButton />
                    <ErrorFilters.SettingsMenu
                        quickFilterContext={QUICK_FILTER_CONTEXT}
                        logicKey={ERROR_TRACKING_SCENE_LOGIC_KEY}
                    />
                </>
            }
        />
    )
}

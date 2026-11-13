import { useValues } from 'kea'

import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { DeprecateSuggestionModal } from './DeprecateSuggestionModal'
import { MaterializeSuggestionModal } from './MaterializeSuggestionModal'
import { SavingsBannerMessage } from './SavingsBannerMessage'
import { SuggestedModelsGroups } from './SuggestedModelsGroups'
import { SuggestionsReviewModal } from './SuggestionsReviewModal'
import { UnmaterializeSuggestionModal } from './UnmaterializeSuggestionModal'

export function SuggestedModelsDialogs(): JSX.Element {
    const { suggestionGroups, savingsSummary, unusedViewCount, status } = useValues(warehouseSuggestionsLogic)

    return (
        <>
            <SuggestionsReviewModal
                title="Suggested models"
                summary={<SavingsBannerMessage summary={savingsSummary} unusedViews={unusedViewCount} />}
            >
                <SuggestedModelsGroups groups={suggestionGroups} windowDays={status?.window_days ?? 0} />
            </SuggestionsReviewModal>
            <MaterializeSuggestionModal />
            <UnmaterializeSuggestionModal />
            <DeprecateSuggestionModal />
        </>
    )
}

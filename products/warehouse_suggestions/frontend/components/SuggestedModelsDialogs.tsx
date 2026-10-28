import { useValues } from 'kea'

import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { MaterializeSuggestionModal } from './MaterializeSuggestionModal'
import { SavingsBannerMessage } from './SavingsBannerMessage'
import { SuggestedModelsGroups } from './SuggestedModelsGroups'
import { SuggestionsReviewModal } from './SuggestionsReviewModal'
import { UnmaterializeSuggestionModal } from './UnmaterializeSuggestionModal'

export function SuggestedModelsDialogs(): JSX.Element {
    const { suggestionGroups, savingsSummary, status } = useValues(warehouseSuggestionsLogic)

    return (
        <>
            <SuggestionsReviewModal
                title="Suggested models"
                summary={<SavingsBannerMessage summary={savingsSummary} />}
            >
                <SuggestedModelsGroups groups={suggestionGroups} windowDays={status?.window_days ?? 0} />
            </SuggestionsReviewModal>
            <MaterializeSuggestionModal />
            <UnmaterializeSuggestionModal />
        </>
    )
}

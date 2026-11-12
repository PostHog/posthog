import { useValues } from 'kea'

import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { QuillDeprecateSuggestionModal } from './QuillDeprecateSuggestionModal'
import { QuillMaterializeSuggestionModal } from './QuillMaterializeSuggestionModal'
import { QuillSuggestedModelsGroups } from './QuillSuggestedModelsGroups'
import { QuillSuggestionsReviewModal } from './QuillSuggestionsReviewModal'
import { QuillUnmaterializeSuggestionModal } from './QuillUnmaterializeSuggestionModal'
import { SavingsBannerMessage } from './SavingsBannerMessage'

export function QuillSuggestedModelsDialogs(): JSX.Element {
    const { suggestionGroups, savingsSummary, unusedViewCount, status } = useValues(warehouseSuggestionsLogic)

    return (
        <>
            <QuillSuggestionsReviewModal
                title="Suggested models"
                summary={<SavingsBannerMessage summary={savingsSummary} unusedViews={unusedViewCount} />}
            >
                <QuillSuggestedModelsGroups groups={suggestionGroups} windowDays={status?.window_days ?? 0} />
            </QuillSuggestionsReviewModal>
            <QuillMaterializeSuggestionModal />
            <QuillUnmaterializeSuggestionModal />
            <QuillDeprecateSuggestionModal />
        </>
    )
}

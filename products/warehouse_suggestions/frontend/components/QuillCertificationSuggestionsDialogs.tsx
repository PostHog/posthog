import { useValues } from 'kea'

import { certificationSummaryText } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { QuillCertificationSuggestionRow } from './QuillCertificationSuggestionRow'
import { QuillDeprecateSuggestionModal } from './QuillDeprecateSuggestionModal'
import { QuillSuggestionsReviewModal } from './QuillSuggestionsReviewModal'

export function QuillCertificationSuggestionsDialogs(): JSX.Element {
    const { listedSuggestions, surfaceSuggestions, status } = useValues(warehouseSuggestionsLogic)
    const windowDays = status?.window_days ?? 0

    return (
        <>
            <QuillSuggestionsReviewModal
                title="Certification suggestions"
                summary={certificationSummaryText(surfaceSuggestions)}
            >
                {listedSuggestions.map((suggestion) => (
                    <QuillCertificationSuggestionRow
                        key={suggestion.id}
                        suggestion={suggestion}
                        windowDays={windowDays}
                    />
                ))}
            </QuillSuggestionsReviewModal>
            <QuillDeprecateSuggestionModal />
        </>
    )
}

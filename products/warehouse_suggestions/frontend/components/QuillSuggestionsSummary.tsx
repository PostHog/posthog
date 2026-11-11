import { useValues } from 'kea'

import { suggestionCountsText } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { SavingsBannerMessage } from './SavingsBannerMessage'

export function QuillSuggestionsSummary(): JSX.Element {
    const { surfaceSuggestions, savingsSummary, unusedViewCount } = useValues(warehouseSuggestionsLogic)
    const certifySuggestions = surfaceSuggestions.filter((suggestion) => suggestion.kind === 'certify')
    const hasModelSuggestions = savingsSummary.views + unusedViewCount > 0

    return (
        <span className="flex flex-col gap-0.5">
            {hasModelSuggestions && <SavingsBannerMessage summary={savingsSummary} unusedViews={unusedViewCount} />}
            {certifySuggestions.length > 0 && <span>{suggestionCountsText(certifySuggestions)}</span>}
        </span>
    )
}

import { useValues } from 'kea'

import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { SavingsBannerMessage } from './SavingsBannerMessage'

export function QuillSuggestionsSummary(): JSX.Element {
    const { surfaceSuggestions, savingsSummary, unusedViewCount } = useValues(warehouseSuggestionsLogic)
    const toCertify = surfaceSuggestions.filter((suggestion) => suggestion.kind === 'certify').length

    return <SavingsBannerMessage summary={savingsSummary} unusedViews={unusedViewCount} toCertify={toCertify} />
}

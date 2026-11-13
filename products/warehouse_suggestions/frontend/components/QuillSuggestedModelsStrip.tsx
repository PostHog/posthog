import { BindLogic, useValues } from 'kea'

import { WarehouseSuggestionsLogicProps, warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { QuillSuggestedModelsDialogs } from './QuillSuggestedModelsDialogs'
import { QuillSuggestionsBanner } from './QuillSuggestionsBanner'
import { QuillSuggestionsStatusNotice } from './QuillSuggestionsStatusNotice'
import { SuggestedModelsStripProps } from './SuggestedModelsStrip'

function QuillSuggestedModelsStripContent(): JSX.Element | null {
    const { stripState } = useValues(warehouseSuggestionsLogic)

    if (stripState !== 'active' && stripState !== 'all_done') {
        return <QuillSuggestionsStatusNotice />
    }

    return (
        <>
            {stripState === 'active' && <QuillSuggestionsBanner />}
            <QuillSuggestedModelsDialogs />
        </>
    )
}

export function QuillSuggestedModelsStrip({
    onAccepted,
    placement = 'models_tab',
}: SuggestedModelsStripProps): JSX.Element {
    const logicProps: WarehouseSuggestionsLogicProps = { surface: 'models', placement, onAccepted }
    return (
        <BindLogic logic={warehouseSuggestionsLogic} props={logicProps}>
            <QuillSuggestedModelsStripContent />
        </BindLogic>
    )
}

import { BindLogic } from 'kea'

import {
    SuggestionPlacement,
    WarehouseSuggestionsLogicProps,
    warehouseSuggestionsLogic,
} from '../warehouseSuggestionsLogic'
import { SuggestedModelsStripContent } from './SuggestedModelsStripContent'

export interface SuggestedModelsStripProps {
    onAccepted?: WarehouseSuggestionsLogicProps['onAccepted']
    placement?: SuggestionPlacement
}

export function SuggestedModelsStrip({
    onAccepted,
    placement = 'models_tab',
}: SuggestedModelsStripProps): JSX.Element | null {
    const logicProps: WarehouseSuggestionsLogicProps = { surface: 'models', placement, onAccepted }
    return (
        <BindLogic logic={warehouseSuggestionsLogic} props={logicProps}>
            <SuggestedModelsStripContent />
        </BindLogic>
    )
}

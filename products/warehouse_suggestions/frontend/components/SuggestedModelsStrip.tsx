import { BindLogic } from 'kea'

import { WarehouseSuggestionsLogicProps, warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { SuggestedModelsStripContent } from './SuggestedModelsStripContent'

export interface SuggestedModelsStripProps {
    onAccepted?: WarehouseSuggestionsLogicProps['onAccepted']
}

export function SuggestedModelsStrip({ onAccepted }: SuggestedModelsStripProps): JSX.Element | null {
    const logicProps: WarehouseSuggestionsLogicProps = { surface: 'models', onAccepted }
    return (
        <BindLogic logic={warehouseSuggestionsLogic} props={logicProps}>
            <SuggestedModelsStripContent />
        </BindLogic>
    )
}

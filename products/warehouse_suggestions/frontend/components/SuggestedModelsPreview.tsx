import { BindLogic } from 'kea'
import { RefObject } from 'react'

import { WarehouseSuggestionsLogicProps, warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { SuggestedModelsPreviewContent } from './SuggestedModelsPreviewContent'

export interface SuggestedModelsPreviewProps {
    onAccepted?: WarehouseSuggestionsLogicProps['onAccepted']
    emptyFocusRef: RefObject<HTMLElement>
}

export function SuggestedModelsPreview({ onAccepted, emptyFocusRef }: SuggestedModelsPreviewProps): JSX.Element {
    const logicProps: WarehouseSuggestionsLogicProps = { surface: 'models', placement: 'overview', onAccepted }
    return (
        <BindLogic logic={warehouseSuggestionsLogic} props={logicProps}>
            <SuggestedModelsPreviewContent emptyFocusRef={emptyFocusRef} />
        </BindLogic>
    )
}

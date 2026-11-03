import { BindLogic } from 'kea'
import { ReactNode, RefObject } from 'react'

import { WarehouseSuggestionsLogicProps, warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { SuggestedModelsPreviewContent } from './SuggestedModelsPreviewContent'

export interface SuggestedModelsPreviewProps {
    onAccepted?: WarehouseSuggestionsLogicProps['onAccepted']
    emptyFocusRef: RefObject<HTMLElement>
    dialogs: ReactNode
}

export function SuggestedModelsPreview({
    onAccepted,
    emptyFocusRef,
    dialogs,
}: SuggestedModelsPreviewProps): JSX.Element {
    const logicProps: WarehouseSuggestionsLogicProps = { surface: 'models', placement: 'overview', onAccepted }
    return (
        <BindLogic logic={warehouseSuggestionsLogic} props={logicProps}>
            <SuggestedModelsPreviewContent emptyFocusRef={emptyFocusRef} dialogs={dialogs} />
        </BindLogic>
    )
}

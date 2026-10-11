import { BindLogic } from 'kea'

import { WarehouseSuggestionsLogicProps, warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { SuggestedCertificationsTableContent } from './SuggestedCertificationsTableContent'

export interface SuggestedCertificationsTableProps {
    onAccepted?: WarehouseSuggestionsLogicProps['onAccepted']
}

export function SuggestedCertificationsTable({ onAccepted }: SuggestedCertificationsTableProps): JSX.Element | null {
    const logicProps: WarehouseSuggestionsLogicProps = { surface: 'catalog', onAccepted }
    return (
        <BindLogic logic={warehouseSuggestionsLogic} props={logicProps}>
            <SuggestedCertificationsTableContent />
        </BindLogic>
    )
}

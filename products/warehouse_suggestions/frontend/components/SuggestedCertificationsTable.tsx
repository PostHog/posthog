import { BindLogic } from 'kea'

import { WarehouseSuggestionsLogicProps, warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { SuggestedCertificationsTableContent } from './SuggestedCertificationsTableContent'

export interface SuggestedCertificationsTableProps {
    onAccepted?: WarehouseSuggestionsLogicProps['onAccepted']
    onViewAccepted?: WarehouseSuggestionsLogicProps['onViewAccepted']
}

export function SuggestedCertificationsTable({
    onAccepted,
    onViewAccepted,
}: SuggestedCertificationsTableProps): JSX.Element | null {
    const logicProps: WarehouseSuggestionsLogicProps = { surface: 'catalog', onAccepted, onViewAccepted }
    return (
        <BindLogic logic={warehouseSuggestionsLogic} props={logicProps}>
            <SuggestedCertificationsTableContent />
        </BindLogic>
    )
}

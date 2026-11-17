import { DailyDigestSection } from '../StamphogDigestsScene/DailyDigestSection'
import { AutoApprovalArea } from './AutoApprovalArea'

export function ApprovalSettings(): JSX.Element {
    return (
        <>
            <AutoApprovalArea />
            <DailyDigestSection />
        </>
    )
}

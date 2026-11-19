import { BindLogic } from 'kea'

import { AfterClickingCard } from './AfterClickingCard'
import { ConversionEventBar } from './ConversionEventBar'
import { emailImpactLogic } from './emailImpactLogic'
import { ImpactFunnelCard } from './ImpactFunnelCard'

export function EmailImpactTab({
    workflowId,
    alwaysSensitive,
}: {
    workflowId: string
    alwaysSensitive: boolean
}): JSX.Element {
    return (
        <BindLogic logic={emailImpactLogic} props={{ workflowId, alwaysSensitive }}>
            <div className="flex flex-col gap-4" data-attr="email-impact-tab">
                <ConversionEventBar />
                <ImpactFunnelCard />
                <AfterClickingCard />
            </div>
        </BindLogic>
    )
}

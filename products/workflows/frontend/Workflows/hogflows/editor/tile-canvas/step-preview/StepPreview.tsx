import type { HogFlowAction } from '../../../types'
import { StepFieldList } from '../StepFieldList'
import type { TileStep } from '../useTileStep'
import { AiPreview } from './AiPreview'
import { BranchPreview } from './BranchPreview'
import { EmailPreview } from './EmailPreview'
import { PersonPreview } from './PersonPreview'
import { SlackPreview } from './SlackPreview'
import { TicketMessagePreview } from './TicketMessagePreview'
import { TicketUpdatePreview } from './TicketUpdatePreview'
import { TimeWindowPreview } from './TimeWindowPreview'
import { WaitPreview } from './WaitPreview'
import { WebhookPreview } from './WebhookPreview'

export function StepPreview({ action, tile }: { action: HogFlowAction; tile: TileStep }): JSX.Element | null {
    const { presentation, color } = tile
    switch (presentation.kind) {
        case 'email':
            return <EmailPreview email={presentation.email} title={`${action.name} preview`} />
        case 'slack':
            return <SlackPreview text={presentation.text} color={color} />
        case 'ai-task':
            return <AiPreview {...presentation} color={color} />
        case 'scout':
            return <AiPreview tools={[]} writes={presentation.writes} color={color} />
        case 'webhook':
            return <WebhookPreview {...presentation} />
        case 'ticket-message':
            return <TicketMessagePreview {...presentation} color={color} />
        case 'ticket-update':
            return <TicketUpdatePreview {...presentation} color={color} />
        case 'person':
            return <PersonPreview properties={presentation.properties} />
        case 'branch':
            return <BranchPreview paths={presentation.paths} />
        case 'wait':
            return <WaitPreview wait={presentation.wait} />
        case 'window':
            return <TimeWindowPreview spans={presentation.window.spans} color={color} />
        case 'fields':
            return <StepFieldList facts={tile.facts} />
    }
}

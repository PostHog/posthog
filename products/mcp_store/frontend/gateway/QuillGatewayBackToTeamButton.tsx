import { IconArrowLeft } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { openGatewayTeamTab } from './GatewayAgentScene'

export function QuillGatewayBackToTeamButton({ onBack }: { onBack?: () => void }): JSX.Element {
    return (
        <Button variant="default" className="self-start" onClick={onBack ?? openGatewayTeamTab}>
            <IconArrowLeft />
            Back to team & agents
        </Button>
    )
}

import { useActions } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { emailDomainAgentLogic } from '../emailDomainAgentLogic'

export function AgentSetupButton(): JSX.Element {
    const { openAgentModal } = useActions(emailDomainAgentLogic)
    return (
        <LemonButton
            type="tertiary"
            icon={<IconSparkles />}
            onClick={openAgentModal}
            data-attr="email-domain-agent-setup"
        >
            Let an agent do it
        </LemonButton>
    )
}

import { LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { JourneyConfidence } from './agentAnalyticsLogic'

const CONFIDENCE_CONFIG: Record<JourneyConfidence, { label: string; tagType: LemonTagType; help: string }> = {
    explicit: {
        label: 'Explicit',
        tagType: 'success',
        help: 'These requests shared a session ID, so they belong to one client session.',
    },
    inferred: {
        label: 'Inferred',
        tagType: 'muted',
        help: 'These requests came from the same client, host, and agent within the inactivity window. They are likely one sequence, but a shared agent IP can mix several clients.',
    },
}

export const AgentJourneyConfidenceTag = ({ confidence }: { confidence: JourneyConfidence }): JSX.Element => {
    const config = CONFIDENCE_CONFIG[confidence]
    return (
        <Tooltip title={config.help}>
            <LemonTag type={config.tagType} size="small">
                {config.label}
            </LemonTag>
        </Tooltip>
    )
}

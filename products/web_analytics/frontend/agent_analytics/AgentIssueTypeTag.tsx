import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { AgentIssueType } from './agentAnalyticsLogic'

const ISSUE_TYPE_CONFIG: Record<AgentIssueType, { label: string; tagType: LemonTagType }> = {
    content_gap: { label: 'Content gap', tagType: 'danger' },
    waste: { label: 'Waste', tagType: 'warning' },
    malformed: { label: 'Malformed', tagType: 'caution' },
}

export const AgentIssueTypeTag = ({ type }: { type: AgentIssueType }): JSX.Element => {
    const config = ISSUE_TYPE_CONFIG[type]
    return <LemonTag type={config.tagType}>{config.label}</LemonTag>
}

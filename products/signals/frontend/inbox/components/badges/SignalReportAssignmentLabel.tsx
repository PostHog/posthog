import { IconPerson } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { IconRobot } from 'lib/lemon-ui/icons'
import { fullName } from 'lib/utils/strings'

import { SignalActorKindEnumApi } from 'products/signals/frontend/generated/api.schemas'

import type { SignalReport } from '../../types'

function assigneeName(assignee: NonNullable<SignalReport['assignee']>): string {
    if (assignee.kind === SignalActorKindEnumApi.Task) {
        return 'PostHog agent'
    }
    if (assignee.kind === SignalActorKindEnumApi.System) {
        return 'PostHog'
    }
    if (assignee.kind === SignalActorKindEnumApi.Agent) {
        return assignee.agent?.trim() || 'External agent'
    }
    return (assignee.user && (fullName(assignee.user) || assignee.user.email)) || 'A teammate'
}

function externalAgentName(assignee: NonNullable<SignalReport['assignee']>): string {
    const agentName = assignee.agent?.trim() || 'external agent'
    const userName = assignee.user?.first_name.trim() || (assignee.user && fullName(assignee.user))

    if (!userName) {
        return agentName
    }

    return `${userName}${userName.endsWith('s') ? "'" : "'s"} ${agentName}`
}

export function SignalReportAssignmentLabel({ report }: { report: SignalReport }): JSX.Element | null {
    const { assignee } = report
    if (!assignee) {
        return null
    }

    const hasPullRequest = !!report.implementation_pr_url
    const isExternalAgent = assignee.kind === SignalActorKindEnumApi.Agent
    const name = isExternalAgent ? externalAgentName(assignee) : assigneeName(assignee)
    const label = hasPullRequest
        ? isExternalAgent
            ? `External PR by ${name}`
            : `PR by ${name}`
        : isExternalAgent
          ? `In progress by ${name}`
          : `Claimed by ${name}`
    const tooltip = isExternalAgent ? `${label}. External agent` : label
    const icon = assignee.kind === SignalActorKindEnumApi.User ? <IconPerson /> : <IconRobot className="size-3.5" />

    return (
        <LemonTag size="small" type="muted" icon={icon} title={tooltip} className="shrink-0 select-none">
            {label}
        </LemonTag>
    )
}

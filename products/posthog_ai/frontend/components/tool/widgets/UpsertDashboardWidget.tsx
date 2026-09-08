import posthog from 'posthog-js'

import { IconDashboard } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { MessageTemplate } from '../../../messages/MessageTemplate'
import { DataToolRow } from '../DataToolRow'
import { GenericMcpToolRenderer } from '../GenericMcpToolRenderer'
import type { ToolRendererProps } from '../toolRegistry'
import {
    extractDashboard,
    extractDashboardCreateRevealTarget,
    extractDashboardMutationRevealTarget,
} from './extractors'

/**
 * Dashboard create / update tool calls. v1 is a status line + "View dashboard" CTA (a full
 * dashboard embed is deliberately deferred). Pre-completion or malformed output falls back to
 * the generic card.
 */
export function UpsertDashboardWidget(props: ToolRendererProps): JSX.Element {
    const { message } = props
    const dashboard = message.status === 'completed' ? extractDashboard(message) : null
    const dashboardTarget =
        message.resolvedKey === 'dashboard-update'
            ? extractDashboardMutationRevealTarget(message)
            : extractDashboardCreateRevealTarget(message)
    const requiresStrictTarget =
        message.resolvedKey === 'dashboard-update' || message.resolvedKey === 'dashboard-create'

    if (!dashboard || (requiresStrictTarget && !dashboardTarget)) {
        return <GenericMcpToolRenderer {...props} />
    }

    const to = dashboardTarget
        ? urls.dashboard(dashboardTarget.dashboardId, undefined, dashboardTarget.tileId)
        : dashboard.id !== undefined
          ? urls.dashboard(dashboard.id)
          : dashboard.url
    const captureReveal = (): void => {
        posthog.capture('posthog ai dashboard reveal clicked', {
            source: 'tool_card',
            target_kind: 'dashboard',
        })
    }

    return (
        <DataToolRow {...props}>
            <MessageTemplate type="ai" wrapperClassName="w-full">
                <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-1.5">
                        <IconDashboard className="text-base" />
                        <span className="min-w-0 truncate font-medium">{dashboard.name || 'Dashboard ready'}</span>
                    </div>
                    {to && (
                        <LemonButton
                            className="shrink-0"
                            to={to}
                            targetBlank
                            size="xsmall"
                            tooltip="Open dashboard"
                            onClick={captureReveal}
                        >
                            View dashboard
                        </LemonButton>
                    )}
                </div>
            </MessageTemplate>
        </DataToolRow>
    )
}

import { IconDashboard } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { MessageTemplate } from '../../../messages/MessageTemplate'
import { DataToolRow } from '../DataToolRow'
import { GenericMcpToolRenderer } from '../GenericMcpToolRenderer'
import type { ToolRendererProps } from '../toolRegistry'
import { extractDashboard, extractDashboardMutationRevealTarget } from './extractors'

/**
 * Dashboard create / update tool calls. v1 is a status line + "View dashboard" CTA (a full
 * dashboard embed is deliberately deferred). Pre-completion or malformed output falls back to
 * the generic card.
 */
export function UpsertDashboardWidget(props: ToolRendererProps): JSX.Element {
    const { message } = props
    const dashboard = message.status === 'completed' ? extractDashboard(message) : null
    const revealTarget = message.status === 'completed' ? extractDashboardMutationRevealTarget(message) : null

    if (!dashboard || (message.resolvedKey === 'dashboard-update' && !revealTarget)) {
        return <GenericMcpToolRenderer {...props} />
    }

    const revealsTile = revealTarget?.tileId !== undefined
    const to = revealsTile
        ? urls.dashboard(revealTarget.dashboardId, undefined, revealTarget.tileId)
        : (dashboard.url ?? (dashboard.id !== undefined ? urls.dashboard(dashboard.id) : undefined))

    return (
        <DataToolRow {...props}>
            <MessageTemplate type="ai" wrapperClassName="w-full">
                <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5">
                        <IconDashboard className="text-base" />
                        <span className="font-medium">{dashboard.name || 'Dashboard ready'}</span>
                    </div>
                    {to && (
                        <LemonButton
                            to={to}
                            targetBlank={!revealsTile}
                            icon={revealsTile ? undefined : <IconOpenInNew />}
                            size="xsmall"
                            tooltip={revealsTile ? undefined : 'Open dashboard'}
                        >
                            {revealsTile ? 'Show on dashboard' : 'View dashboard'}
                        </LemonButton>
                    )}
                </div>
            </MessageTemplate>
        </DataToolRow>
    )
}

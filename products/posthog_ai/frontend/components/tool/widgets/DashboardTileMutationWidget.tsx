import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { MessageTemplate } from '../../../messages/MessageTemplate'
import { DataToolRow } from '../DataToolRow'
import { GenericMcpToolRenderer } from '../GenericMcpToolRenderer'
import type { ToolRendererProps } from '../toolRegistry'
import { extractDashboardMutationRevealTarget } from './extractors'

export function DashboardTileMutationWidget(props: ToolRendererProps): JSX.Element {
    const target = props.message.status === 'completed' ? extractDashboardMutationRevealTarget(props.message) : null

    if (!target) {
        return <GenericMcpToolRenderer {...props} />
    }

    const revealsTile = target.tileId !== undefined
    const to = urls.dashboard(target.dashboardId, undefined, target.tileId)

    return (
        <DataToolRow {...props}>
            <MessageTemplate type="ai" wrapperClassName="w-full">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium">Dashboard updated</span>
                    <LemonButton
                        to={to}
                        size="xsmall"
                        data-attr={revealsTile ? 'posthog-ai-show-dashboard-tile' : 'posthog-ai-view-dashboard'}
                    >
                        {revealsTile ? 'Show on dashboard' : 'View dashboard'}
                    </LemonButton>
                </div>
            </MessageTemplate>
        </DataToolRow>
    )
}

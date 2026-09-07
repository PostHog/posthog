import { combineUrl } from 'kea-router'
import posthog from 'posthog-js'

import { IconDashboard } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { MessageTemplate } from '../../../messages/MessageTemplate'
import { DataToolRow } from '../DataToolRow'
import { GenericMcpToolRenderer } from '../GenericMcpToolRenderer'
import type { ToolRendererProps } from '../toolRegistry'
import { extractDashboardMutationRevealTarget } from './extractors'

/**
 * Displays an authoritative dashboard mutation with a direct route to its affected tile or dashboard.
 * Any incomplete or ambiguous result stays on the generic card to avoid suggesting a false target.
 */
export function DashboardTileMutationWidget(props: ToolRendererProps): JSX.Element {
    const { message } = props
    const target = extractDashboardMutationRevealTarget(message)

    if (!target) {
        return <GenericMcpToolRenderer {...props} />
    }

    const revealsTile = target.tileId !== undefined
    const to = revealsTile
        ? combineUrl(urls.dashboard(target.dashboardId), { highlightTileId: target.tileId }).url
        : urls.dashboard(target.dashboardId)
    const captureReveal = (): void => {
        posthog.capture('posthog ai dashboard reveal clicked', {
            source: 'tool_card',
            target_kind: revealsTile ? 'tile' : 'dashboard',
        })
    }

    return (
        <DataToolRow {...props}>
            <MessageTemplate type="ai" wrapperClassName="w-full">
                <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-1.5">
                        <IconDashboard className="text-base" />
                        <span className="min-w-0 truncate font-medium">Dashboard updated</span>
                    </div>
                    <LemonButton
                        className="shrink-0"
                        to={to}
                        targetBlank={!revealsTile}
                        size="xsmall"
                        onClick={captureReveal}
                    >
                        {revealsTile ? 'Show on dashboard' : 'View dashboard'}
                    </LemonButton>
                </div>
            </MessageTemplate>
        </DataToolRow>
    )
}

import { combineUrl } from 'kea-router'

import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ActivityScope } from '~/types'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

/**
 * A scout's last status change, such as who turned it off, and where the rest of the story is. The row records only
 * the last change, so every earlier toggle is the activity log's to tell.
 */
export function ScoutStatusChangeLine({
    config,
    line,
}: {
    config: SignalScoutConfig
    line: string | null
}): JSX.Element | null {
    if (!line) {
        return null
    }
    const activityUrl = combineUrl(urls.advancedActivityLogs(), {
        scopes: ActivityScope.SIGNAL_SCOUT_CONFIG,
        item_ids: config.id,
    }).url
    return (
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-secondary">
            <span>{line}</span>
            <Link to={activityUrl} className="text-xs">
                See every change
            </Link>
        </div>
    )
}

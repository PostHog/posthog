import { IconTelescope } from '@posthog/icons'

import { slackChannelName } from 'lib/integrations/slackChannel'
import { IconSlack } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { urls } from 'scenes/urls'

import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'
import { scoutDisplayName } from 'products/signals/frontend/inbox/utils/scoutRunsWindow'

export function DashboardScoutListItem({ scout }: { scout: SignalScoutConfigApi }): JSX.Element {
    const channel = scout.output_destinations?.slack?.channel
    const channelName = channel ? slackChannelName(channel) : undefined

    return (
        <LemonButton
            type="secondary"
            to={urls.inboxScout(scout.skill_name)}
            icon={<IconTelescope />}
            fullWidth
            data-attr="dashboard-scout-list-item"
        >
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2 p-2">
                <span className="font-medium truncate">{scoutDisplayName(scout)}</span>
                <LemonTag size="small">Scout</LemonTag>
                {!scout.enabled && (
                    <LemonTag type="danger" size="small">
                        Paused
                    </LemonTag>
                )}
                {channelName ? (
                    <span className="ml-auto flex items-center gap-1 text-xs text-secondary">
                        <IconSlack />
                        <span className="max-w-40 truncate">#{channelName}</span>
                    </span>
                ) : null}
            </div>
        </LemonButton>
    )
}

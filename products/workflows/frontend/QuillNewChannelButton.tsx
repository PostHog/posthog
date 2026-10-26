import { useActions, useValues } from 'kea'

import { IconApple, IconAndroid, IconLetter, IconPlus } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import api from 'lib/api'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { FEATURE_FLAGS, TeamMembershipLevel } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IconSlack, IconTwilio } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export function QuillNewChannelButton({ channelsUrl }: { channelsUrl: string }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { openSetupModal } = useActions(integrationsLogic)
    const newChannelRestrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        data-attr="new-channel-button"
                        variant="primary"
                        disabledReason={newChannelRestrictedReason}
                    />
                }
            >
                <IconPlus />
                New channel
            </DropdownMenuTrigger>
            <DropdownMenuContent>
                <DropdownMenuItem onClick={() => openSetupModal(undefined, 'email')}>
                    <IconLetter />
                    Email
                </DropdownMenuItem>
                <DropdownMenuItem
                    onClick={() => {
                        // The Slack OAuth flow leaves the app, so this is a full page load.
                        window.location.href = api.integrations.authorizeUrl({ kind: 'slack', next: channelsUrl })
                    }}
                >
                    <IconSlack />
                    Slack
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => openSetupModal(undefined, 'twilio')}>
                    <IconTwilio />
                    Twilio
                </DropdownMenuItem>
                {featureFlags[FEATURE_FLAGS.WORKFLOWS_PUSH_NOTIFICATIONS] && (
                    <>
                        <DropdownMenuItem onClick={() => openSetupModal(undefined, 'firebase')}>
                            <IconAndroid />
                            Firebase Cloud Messaging
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => openSetupModal(undefined, 'apns')}>
                            <IconApple />
                            Apple Push Notifications
                        </DropdownMenuItem>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

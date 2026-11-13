import { useActions, useValues } from 'kea'

import { IconLetter, IconPlus } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

import { channelCatalogLogic } from './channelCatalogLogic'
import { sandboxSenderLogic } from './sandboxSenderLogic'

export function SandboxEmailSenderRow(): JSX.Element | null {
    const { sandboxStatus } = useValues(sandboxSenderLogic)
    const { startChannelSetup } = useActions(channelCatalogLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    if (!sandboxStatus?.integration_id || !sandboxStatus.from_address) {
        return null
    }
    const fromLine = `${sandboxStatus.display_name} <${sandboxStatus.from_address}>`

    return (
        <LemonCard hoverEffect={false} className="p-2 @container" data-attr="sandbox-email-sender">
            <div className="flex flex-col items-start gap-3 ml-2 @lg:flex-row @lg:items-center">
                <div className="flex flex-1 gap-4 items-start w-full min-w-0">
                    <IconLetter className="w-8 h-8 shrink-0" />
                    <div className="flex flex-col gap-1 min-w-0">
                        <div className="flex flex-wrap gap-2 items-center">
                            <strong>Sandbox sender</strong>
                            <span className="text-xs text-secondary truncate" translate="no" title={fromLine}>
                                {fromLine}
                            </span>
                        </div>
                        <span className="text-sm text-secondary">
                            Sends from a PostHog address, so it works before you verify a domain. It only delivers to
                            verified members of your organization. Add your own sender to email anyone.
                        </span>
                    </div>
                </div>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconPlus />}
                    className="shrink-0"
                    onClick={() => startChannelSetup('email')}
                    disabledReason={restrictedReason}
                    data-attr="sandbox-email-sender-add-own"
                >
                    Add your own sender
                </LemonButton>
            </div>
        </LemonCard>
    )
}

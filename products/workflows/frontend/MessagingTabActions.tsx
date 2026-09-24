import { useActions, useValues } from 'kea'

import { IconApple, IconAndroid, IconLetter, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItems } from '@posthog/lemon-ui'

import api from 'lib/api'
import { AccessControlAction } from 'lib/components/AccessControlAction'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { FEATURE_FLAGS, TeamMembershipLevel } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IconSlack, IconTwilio } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { MessagingNavTabKey } from './messagingTabs'
import { optOutCategoriesLogic } from './OptOuts/optOutCategoriesLogic'

/** The scene-header action for a shared messaging tab, the same on every surface that shows the tab. */
export function MessagingTabActions({
    tab,
    channelsUrl,
}: {
    tab: MessagingNavTabKey
    /** Where the Slack authorization flow returns to, so it lands back on the surface it left. */
    channelsUrl: string
}): JSX.Element | null {
    // One component per action, so a tab mounts (and loads) only the logic its own button needs.
    if (tab === 'library') {
        return <NewTemplateButton />
    }
    if (tab === 'channels') {
        return <NewChannelButton channelsUrl={channelsUrl} />
    }
    if (tab === 'opt-outs') {
        return <NewCategoryButton />
    }
    return null
}

function NewTemplateButton(): JSX.Element {
    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Workflow}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <LemonButton
                data-attr="new-message-button"
                to={urls.workflowsLibraryTemplateNew()}
                type="primary"
                size="small"
            >
                New template
            </LemonButton>
        </AccessControlAction>
    )
}

function NewChannelButton({ channelsUrl }: { channelsUrl: string }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { openSetupModal } = useActions(integrationsLogic)
    const newChannelRestrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const newChannelMenuItems: LemonMenuItems = [
        {
            label: (
                <div className="flex gap-1 items-center">
                    <IconLetter /> Email
                </div>
            ),
            onClick: () => openSetupModal(undefined, 'email'),
        },

        {
            label: (
                <div className="flex gap-1 items-center">
                    <IconSlack /> Slack
                </div>
            ),
            disableClientSideRouting: true,
            to: api.integrations.authorizeUrl({
                kind: 'slack',
                next: channelsUrl,
            }),
        },
        {
            label: (
                <div className="flex gap-1 items-center">
                    <IconTwilio /> Twilio
                </div>
            ),
            onClick: () => openSetupModal(undefined, 'twilio'),
        },
        ...(featureFlags[FEATURE_FLAGS.WORKFLOWS_PUSH_NOTIFICATIONS]
            ? [
                  {
                      label: (
                          <div className="flex gap-1 items-center">
                              <IconAndroid /> Firebase Cloud Messaging
                          </div>
                      ),
                      onClick: () => openSetupModal(undefined, 'firebase'),
                  },
                  {
                      label: (
                          <div className="flex gap-1 items-center">
                              <IconApple /> Apple Push Notifications
                          </div>
                      ),
                      onClick: () => openSetupModal(undefined, 'apns'),
                  },
              ]
            : []),
    ]

    return (
        <LemonMenu items={newChannelMenuItems} matchWidth>
            <LemonButton
                data-attr="new-channel-button"
                icon={<IconPlusSmall />}
                size="small"
                type="primary"
                disabledReason={newChannelRestrictedReason}
            >
                New channel
            </LemonButton>
        </LemonMenu>
    )
}

function NewCategoryButton(): JSX.Element {
    const { openNewCategoryModal } = useActions(optOutCategoriesLogic)

    return (
        <LemonButton
            data-attr="new-optout-category"
            icon={<IconPlusSmall />}
            size="small"
            type="primary"
            onClick={() => openNewCategoryModal()}
        >
            New category
        </LemonButton>
    )
}

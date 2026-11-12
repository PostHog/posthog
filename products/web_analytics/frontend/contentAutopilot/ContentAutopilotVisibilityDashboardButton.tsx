import { useActions, useValues } from 'kea'

import { IconDashboard } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { contentAutopilotVisibilityDashboardLogic } from './contentAutopilotVisibilityDashboardLogic'

export const ContentAutopilotVisibilityDashboardButton = (): JSX.Element => {
    const { creatingVisibilityDashboard } = useValues(contentAutopilotVisibilityDashboardLogic)
    const { createVisibilityDashboard } = useActions(contentAutopilotVisibilityDashboardLogic)

    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconDashboard />}
            onClick={createVisibilityDashboard}
            loading={creatingVisibilityDashboard}
            disabledReason={
                getAccessControlDisabledReason(AccessControlResourceType.Dashboard, AccessControlLevel.Editor) ??
                getAccessControlDisabledReason(AccessControlResourceType.Insight, AccessControlLevel.Editor)
            }
            tooltip="Creates a dashboard of weekly non-branded visibility, topics and pages to watch, which you can subscribe to in Slack or email."
            data-attr="content-autopilot-create-visibility-dashboard"
        >
            Create AI visibility dashboard
        </LemonButton>
    )
}

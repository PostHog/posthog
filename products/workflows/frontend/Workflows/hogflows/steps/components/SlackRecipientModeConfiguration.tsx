import { useValues } from 'kea'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { SlackRecipientMode } from '../slackRecipientMode'

export function SlackRecipientModeConfiguration({
    mode,
    onChange,
}: {
    mode: SlackRecipientMode
    onChange: (mode: SlackRecipientMode) => void
}): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    // A step that already messages a team member keeps the switch, so it can go back to a channel with the flag off.
    if (!featureFlags[FEATURE_FLAGS.WORKFLOW_SLACK_DM_TEAM_MEMBER_ACTION] && mode !== 'team_member') {
        return null
    }

    return (
        <LemonField.Pure
            label="Send to"
            info="A team member gets a direct message from the PostHog bot. They must be a member of this project."
        >
            <LemonSegmentedButton<SlackRecipientMode>
                fullWidth
                value={mode}
                onChange={onChange}
                options={[
                    { value: 'channel', label: 'Channel' },
                    { value: 'team_member', label: 'Team member' },
                ]}
                data-attr="workflow-slack-recipient-mode"
            />
        </LemonField.Pure>
    )
}

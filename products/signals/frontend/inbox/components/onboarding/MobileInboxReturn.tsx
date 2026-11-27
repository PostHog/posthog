import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { getMobileInboxReturn } from '../../utils/mobileInboxReturn'

export function MobileInboxReturn(): JSX.Element | null {
    const { currentTeamId } = useValues(teamLogic)
    const url = getMobileInboxReturn(currentTeamId)
    if (!url) {
        return null
    }
    return (
        <LemonButton
            type="primary"
            onClick={() => {
                window.location.href = url
            }}
            data-attr="inbox-return-to-mobile"
        >
            Return to PostHog mobile
        </LemonButton>
    )
}

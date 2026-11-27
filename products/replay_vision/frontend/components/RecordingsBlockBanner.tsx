import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import { RECORDINGS_BLOCK_CAUSE, replayRecordingsLogic } from '../logics/replayRecordingsLogic'

export function RecordingsBlockBanner(): JSX.Element | null {
    const { recordingsBlock } = useValues(replayRecordingsLogic)
    const { currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    // Same gate as the settings toggle that writes this field (`ReplayGeneral`).
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    if (recordingsBlock === 'replay-off') {
        return (
            <LemonBanner
                type="warning"
                action={{
                    children: 'Turn on session replay',
                    onClick: () => updateCurrentTeam({ session_recording_opt_in: true }),
                    loading: currentTeamLoading,
                    disabledReason: restrictedReason ? 'Ask a project admin to turn on session replay' : null,
                    'data-attr': 'vision-recordings-banner-enable-replay',
                }}
            >
                {RECORDINGS_BLOCK_CAUSE['replay-off']}, so scanners have no recordings to watch. Scanners start again
                when recording is on.
            </LemonBanner>
        )
    }
    if (recordingsBlock === 'no-recordings') {
        return (
            <LemonBanner
                type="warning"
                action={{
                    children: 'Set up session replay',
                    to: urls.onboarding({ productKey: ProductKey.SESSION_REPLAY, stepKey: OnboardingStepKey.INSTALL }),
                    'data-attr': 'vision-recordings-banner-setup-replay',
                }}
            >
                {RECORDINGS_BLOCK_CAUSE['no-recordings']}, so scanners have nothing to watch. Check that session replay
                is installed and capturing sessions.
            </LemonBanner>
        )
    }
    return null
}

import { useActions, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { inboxSetupLogic } from '../../logics/inboxSetupLogic'

export function InboxSetupContinueButton(): JSX.Element {
    const { draft, ready, saving, isFinalStep, activationDisabledReason, activatesWithoutGithub } =
        useValues(inboxSetupLogic)
    const { goToStep, requestActivation } = useActions(inboxSetupLogic)
    const shared = { className: 'ml-auto', loading: saving, 'data-attr': 'inbox-setup-continue' }
    if (!isFinalStep) {
        return (
            <LemonButton
                {...shared}
                type="primary"
                status="alt"
                disabledReason={ready ? undefined : 'Loading your setup'}
                sideIcon={<IconArrowRight />}
                onClick={() => goToStep(draft.step === 'signals' ? 'scouts' : 'github')}
            >
                {draft.step === 'signals' ? 'Continue to scouts' : 'Continue'}
            </LemonButton>
        )
    }
    return (
        <LemonButton
            {...shared}
            type={activatesWithoutGithub ? 'secondary' : 'primary'}
            status={activatesWithoutGithub ? 'default' : 'alt'}
            disabledReason={ready ? activationDisabledReason : 'Loading your setup'}
            onClick={() => requestActivation()}
        >
            {activatesWithoutGithub ? 'Activate without GitHub' : 'Activate Self-driving'}
        </LemonButton>
    )
}

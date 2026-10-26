import { useActions, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TerminalCard } from 'lib/components/CommandBlock/TerminalCard'

import { captureInboxWelcomeCommandCopied } from '../../inboxAnalytics'
import { inboxSetupLogic } from '../../logics/inboxSetupLogic'
import { SELF_DRIVING_WIZARD_COMMAND } from '../../utils/selfDrivingWizardCommand'
import { InboxQuickSetupAction } from './InboxQuickSetupAction'

export function InboxSetupActions(): JSX.Element {
    const { continueFromWelcome } = useActions(inboxSetupLogic)
    const { isTreatment, isQuickSetup } = useValues(inboxSetupLogic)

    return (
        <div className="flex w-full min-w-0 flex-col gap-4">
            {!isTreatment && (
                <div className="flex min-w-0 flex-col gap-2">
                    <p className="m-0 text-sm text-secondary">
                        Install with Wizard. Run the setup agent in your repository to connect GitHub and choose your
                        signals and scouts.
                    </p>
                    <TerminalCard
                        command={SELF_DRIVING_WIZARD_COMMAND}
                        copyLabel="self-driving setup command"
                        onCopy={() => captureInboxWelcomeCommandCopied({ surface: 'takeover' })}
                    />
                </div>
            )}
            {isQuickSetup ? (
                <InboxQuickSetupAction />
            ) : (
                // pinned: autocapture data-attr - dashboards and test selectors match on this string
                <div data-attr="inbox-welcome-set-up-manually" className="self-start">
                    <LemonButton
                        type={isTreatment ? 'primary' : 'secondary'}
                        status={isTreatment ? 'alt' : undefined}
                        sideIcon={<IconArrowRight />}
                        onClick={continueFromWelcome}
                        // pinned: data-attr - the welcome funnel and test selectors match on this string
                        data-attr="inbox-setup-welcome-continue"
                    >
                        {isTreatment ? 'Set up Self-Driving' : 'Start manually'}
                    </LemonButton>
                </div>
            )}
        </div>
    )
}

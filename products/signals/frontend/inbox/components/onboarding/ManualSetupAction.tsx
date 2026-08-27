import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { InboxWelcomeVariant } from '../../inboxAnalytics'
import { inboxOnboardingLogic } from '../../logics/inboxOnboardingLogic'

/**
 * The takeover's escape hatch: skip the setup agent and turn sources and scouts on by hand.
 *
 * Both welcome arms render it, from here rather than each writing their own, so the label and the
 * helper line cannot drift between the arms of a live experiment. `variant` says which arm the
 * press came from; the parent places the block with `className`.
 */
export function ManualSetupAction({
    variant,
    className,
}: {
    variant: InboxWelcomeVariant
    className?: string
}): JSX.Element {
    const { requestManualSetup } = useActions(inboxOnboardingLogic)

    return (
        <div className={`flex flex-col gap-2 ${className ?? ''}`}>
            <LemonButton
                type="secondary"
                // pinned: autocapture data-attr - dashboards and test selectors match on this string
                data-attr="inbox-welcome-set-up-manually"
                className="w-fit"
                onClick={() => requestManualSetup(variant)}
            >
                Set up manually
            </LemonButton>
            <p className="m-0 max-w-prose text-[13px] text-tertiary">
                Turn on sources and scouts yourself in Configuration. You still need to connect GitHub for pull
                requests.
            </p>
        </div>
    )
}

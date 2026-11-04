import { useActions } from 'kea'

import { IconPause, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { inboxOnboardingLogic } from '../../logics/inboxOnboardingLogic'
import { inboxSetupLogic } from '../../logics/inboxSetupLogic'

export function InboxOnboardingBanner(): JSX.Element {
    const { openSetup } = useActions(inboxSetupLogic)
    const { dismissBanner } = useActions(inboxOnboardingLogic)

    return (
        <div className="mx-4 mb-3 mt-2 flex flex-col gap-2 rounded-lg border border-dashed border-primary bg-bg-light p-4">
            <div className="flex items-center gap-2 -my-1">
                <IconPause className="size-4 shrink-0 text-accent" />
                <h4 className="m-0 flex-1 text-sm font-semibold">Self-driving is paused</h4>
                <LemonButton
                    size="xsmall"
                    icon={<IconX />}
                    tooltip="Dismiss for now"
                    aria-label="Dismiss self-driving reminder"
                    onClick={dismissBanner}
                />
            </div>
            <p className="mb-0.5 text-sm text-tertiary">Choose sources and scouts to start receiving reports again.</p>
            <LemonButton type="primary" className="w-fit" onClick={openSetup} data-attr="inbox-paused-set-up">
                Set up Self-Driving
            </LemonButton>
        </div>
    )
}

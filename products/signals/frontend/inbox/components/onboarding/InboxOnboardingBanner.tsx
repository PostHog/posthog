import { useActions, useValues } from 'kea'

import { IconPause, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'

import { captureInboxWelcomeCommandCopied } from '../../inboxAnalytics'
import { inboxOnboardingLogic } from '../../logics/inboxOnboardingLogic'
import { inboxSetupLogic } from '../../logics/inboxSetupLogic'
import { SELF_DRIVING_WIZARD_COMMAND } from './InboxWelcome'

export function InboxOnboardingBanner(): JSX.Element {
    const { isTreatment } = useValues(inboxSetupLogic)
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
            {isTreatment ? (
                <>
                    <p className="mb-0.5 text-sm text-tertiary">
                        Choose signals and scouts to start receiving reports again.
                    </p>
                    <LemonButton type="primary" className="w-fit" onClick={openSetup}>
                        Set up Self-Driving
                    </LemonButton>
                </>
            ) : (
                <>
                    <p className="mb-0.5 text-sm text-tertiary">
                        No scouts or sources are enabled right now.{' '}
                        <strong>Switch self-driving back on with one command in your product's repo:</strong>
                    </p>
                    <CommandBlock
                        command={SELF_DRIVING_WIZARD_COMMAND}
                        copyLabel="self-driving setup command"
                        ariaLabel="Copy self-driving setup command"
                        decoration="rainbow"
                        size="sm"
                        onCopy={() => captureInboxWelcomeCommandCopied({ surface: 'banner' })}
                        className="!m-0 rounded-md border border-primary bg-surface-secondary hover:border-accent"
                    />
                </>
            )}
        </div>
    )
}

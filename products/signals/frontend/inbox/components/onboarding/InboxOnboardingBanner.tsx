import { useActions } from 'kea'

import { IconPause, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'

import { captureInboxWelcomeCommandCopied } from '../../inboxAnalytics'
import { inboxOnboardingLogic } from '../../logics/inboxOnboardingLogic'
import { SELF_DRIVING_WIZARD_COMMAND } from './InboxWelcome'

/**
 * Sleek, non-blocking nudge shown above the inbox when self-driving isn't set up but reports or
 * PRs already exist (they had sources/scouts before). Keeps full access to existing work while
 * enticing a re-enable via the same one command. Styled as an "enable a capability" card (à la the
 * MCP use-case hint) rather than a system banner; session-dismissable via the close button.
 */
export function InboxOnboardingBanner(): JSX.Element {
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
            <p className="mb-0.5 text-sm text-tertiary">
                No scouts or sources are enabled right now.{' '}
                <strong>Switch self-driving back on with one command in your product's repo:</strong>
            </p>
            {/* The wizard command as a click-to-copy pill. Reuses the shared `CommandBlock` (same one
                MCP install uses) with the `rainbow` AI gradient, so it reads as "enable a capability"
                rather than a code dump. */}
            <CommandBlock
                command={SELF_DRIVING_WIZARD_COMMAND}
                copyLabel="self-driving setup command"
                ariaLabel="Copy self-driving setup command"
                decoration="rainbow"
                size="sm"
                onCopy={() => captureInboxWelcomeCommandCopied({ surface: 'banner' })}
                // rounded-md sits one step inside the rounded-lg banner it nests in.
                className="!m-0 rounded-md border border-primary bg-surface-secondary hover:border-accent"
            />
        </div>
    )
}

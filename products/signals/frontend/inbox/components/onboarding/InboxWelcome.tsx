import './InboxWelcome.scss'

import { useActions, useMountedLogic, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { useEffect, useRef, useState } from 'react'

import { IconCheck } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { Logomark } from 'lib/brand'
import { FEATURE_FLAGS } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { GithubIntegration } from 'scenes/integrations/components/GithubIntegration'
import { urls } from 'scenes/urls'

import { captureInboxWelcomeCommandCopied, captureInboxWelcomeViewed } from '../../inboxAnalytics'
import { inboxOnboardingLogic } from '../../logics/inboxOnboardingLogic'
import { LoopDiagram } from './LoopDiagram'

/** The one command that sets up self-driving. The whole onboarding orbits this string. */
export const SELF_DRIVING_WIZARD_COMMAND = 'npx -y @posthog/wizard@latest self-driving'

/** How long the copy button reads "Copied" before flipping back. */
const COPIED_RESET_MS = 1600

/**
 * The hero CTA: the wizard command on a near-black block with a single yellow copy button.
 * The button is its own feedback ("Copy" -> "Copied"), so the clipboard toast is suppressed.
 */
function CommandCta(): JSX.Element {
    const [copied, setCopied] = useState(false)
    const resetTimerRef = useRef<number | null>(null)

    useEffect(() => {
        return () => {
            if (resetTimerRef.current !== null) {
                window.clearTimeout(resetTimerRef.current)
            }
        }
    }, [])

    const handleCopy = (): void => {
        void copyToClipboard(SELF_DRIVING_WIZARD_COMMAND, 'self-driving setup command', { silent: true })
        captureInboxWelcomeCommandCopied({ surface: 'takeover' })
        setCopied(true)
        if (resetTimerRef.current !== null) {
            window.clearTimeout(resetTimerRef.current)
        }
        resetTimerRef.current = window.setTimeout(() => setCopied(false), COPIED_RESET_MS)
    }

    return (
        <div className="InboxWelcome__cta flex flex-wrap items-center justify-center gap-x-3 gap-y-2.5 py-2.5 pl-4 pr-2.5">
            <span className="whitespace-nowrap font-mono text-sm text-white">
                <span className="select-none text-[#6f6f76]">$ </span>
                {SELF_DRIVING_WIZARD_COMMAND}
            </span>
            <button
                type="button"
                className="InboxWelcome__copy-button"
                onClick={handleCopy}
                aria-label="Copy self-driving setup command"
            >
                {copied ? 'Copied' : 'Copy'}
            </button>
        </div>
    )
}

function GithubFirstCta(): JSX.Element {
    useMountedLogic(integrationsLogic)
    const { githubIntegrations, integrationsLoading } = useValues(integrationsLogic)
    const hasGithubIntegration = githubIntegrations.some(
        (integration) => integration.installation_status !== 'unavailable'
    )

    if (integrationsLoading) {
        return <LemonSkeleton className="h-10 w-64 rounded" />
    }

    if (hasGithubIntegration) {
        return (
            <>
                <div className="mb-4">
                    <LemonTag type="success" icon={<IconCheck />}>
                        GitHub connected
                    </LemonTag>
                </div>
                <h2 className="mb-4 text-lg font-semibold">Almost there</h2>
                <CommandCta />
                <p className="mt-3.5 max-w-[520px] text-[13px] text-tertiary">
                    Run the setup agent in your repo to pick the signal sources and scouts to watch. PRs start landing
                    in this inbox.
                </p>
            </>
        )
    }

    return (
        <div className="w-full max-w-[560px] text-left">
            <GithubIntegration
                next={combineUrl(urls.inbox(), { setup: 'github-first' }).url}
                connectSurface="inbox_welcome"
                connectText="Connect GitHub"
                emphasizeConnect
                showPersonalConnectionHelp={false}
            />
        </div>
    )
}

/** The escape hatch: skip the setup agent and turn sources and scouts on by hand. */
function ManualSetupAction(): JSX.Element {
    const { requestManualSetup } = useActions(inboxOnboardingLogic)

    return (
        <div className="mt-7 flex flex-col items-center gap-2 text-center">
            <LemonButton
                type="secondary"
                // pinned: autocapture data-attr - dashboards and test selectors match on this string
                data-attr="inbox-welcome-set-up-manually"
                className="w-fit"
                onClick={() => requestManualSetup()}
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

/**
 * Self-driving welcome takeover, shown when self-driving isn't set up and there's nothing in the
 * inbox yet. Leads with the payoff, makes the wizard command the one CTA, and explains signal
 * sources and the scouts & pipeline stage as labels over an animated loop instead of prose.
 * Rendered in place of the report list and without the tab bar: a full-pane welcome, not a tab.
 */
export function InboxWelcome(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const githubFirst = !!featureFlags[FEATURE_FLAGS.GITHUB_FIRST_SELF_DRIVING_ONBOARDING]

    useEffect(() => {
        captureInboxWelcomeViewed()
    }, [])

    return (
        <div className="InboxWelcome flex min-h-full flex-col justify-center py-10">
            <div className="px-6 pb-12">
                <div className="mx-auto flex max-w-[720px] flex-col items-center text-center">
                    <div className="mb-7">
                        <Logomark jumpOnClick size="xl" />
                    </div>
                    <h1 className="mb-4 text-2xl font-bold leading-[1.1] tracking-[-0.02em] sm:text-[32px]">
                        Ship fixes while you sleep
                    </h1>
                    <p className="mb-9 max-w-[560px] text-[15px] leading-[1.55] text-secondary">
                        PostHog watches your session replays, errors, and Slack. When it finds something worth fixing,
                        it writes the pull request. You review and merge.
                    </p>
                    {githubFirst ? (
                        <GithubFirstCta />
                    ) : (
                        <>
                            <CommandCta />
                            <p className="mt-3.5 max-w-[520px] text-[13px] text-tertiary">
                                Run it in your repo. That's the whole setup: it connects GitHub and picks the signal
                                sources and scouts to watch. PRs start landing in this inbox.
                            </p>
                        </>
                    )}
                    <ManualSetupAction />
                </div>
            </div>
            <div className="px-6 md:px-12">
                <div className="mx-auto max-w-[1060px]">
                    <LoopDiagram />
                    <p className="mt-6 text-center text-xs text-tertiary">
                        Your first 3 PRs each month are free, then $15 per PR. Reports are always free.
                    </p>
                </div>
            </div>
        </div>
    )
}

import { useActions, useValues } from 'kea'

import { IconLock } from '@posthog/icons'
import { LemonButton, LemonModal, Link } from '@posthog/lemon-ui'

import { inboxSetupLogic } from '../../logics/inboxSetupLogic'
import { InboxGithubAccessReasons } from './InboxGithubAccessReasons'
import { InboxSetupGithubConnect } from './InboxSetupGithubConnect'

interface InboxSetupGithubSkipDialogProps {
    canConnectGithub: boolean
}

export function InboxSetupGithubSkipDialog({ canConnectGithub }: InboxSetupGithubSkipDialogProps): JSX.Element {
    const { githubSkipConfirmationVisible, githubIntegrations } = useValues(inboxSetupLogic)
    const { setGithubSkipConfirmationOpen, activate } = useActions(inboxSetupLogic)
    return (
        <LemonModal
            isOpen={githubSkipConfirmationVisible}
            onClose={() => setGithubSkipConfirmationOpen(false)}
            title="Activate without GitHub?"
            width={640}
            data-attr="inbox-setup-skip-github-dialog"
            footer={
                // Bottom-aligned because the connect card adds a notice above its button for a linkable installation.
                <div className="flex w-full flex-wrap items-end justify-end gap-2">
                    <LemonButton
                        type="secondary"
                        onClick={() => activate()}
                        data-attr="inbox-setup-skip-github-confirm"
                    >
                        Activate without GitHub
                    </LemonButton>
                    {/* The connect card lists an existing connection, and a list does not fit this row of buttons.
                        One exists when GitHub reports it as unavailable, and briefly after a link from this dialog. */}
                    {canConnectGithub && githubIntegrations.length === 0 && (
                        <div className="min-w-0 whitespace-normal">
                            <InboxSetupGithubConnect connectDescription="" />
                        </div>
                    )}
                </div>
            }
        >
            <div className="flex flex-col gap-3 text-sm text-secondary">
                <InboxGithubAccessReasons
                    pullRequests={{
                        title: 'Pull requests only when you ask.',
                        description:
                            'We open one when you click Implement with PostHog on a report, or after you turn on PR generation. You review and merge each one.',
                    }}
                />
                <p className="m-0 flex items-start gap-1.5">
                    <IconLock className="mt-0.5 shrink-0 text-base" />
                    <span>
                        We don't train models on your code. Read about code access, storage and GitHub permissions in
                        the{' '}
                        <Link
                            to="https://posthog.com/docs/self-driving/security"
                            target="_blank"
                            data-attr="inbox-setup-github-security"
                        >
                            security docs
                        </Link>
                        .
                    </span>
                </p>
            </div>
        </LemonModal>
    )
}

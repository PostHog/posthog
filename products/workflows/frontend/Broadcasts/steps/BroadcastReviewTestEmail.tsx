import { useActions, useMountedLogic, useValues } from 'kea'

import { IconCheckCircle, IconSend } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { broadcastTestSendLogic } from '../broadcastTestSendLogic'
import { broadcastWizardLogic } from '../broadcastWizardLogic'

export function BroadcastReviewTestEmail(): JSX.Element {
    const { props } = useMountedLogic(broadcastWizardLogic)
    const { lastTestSentTo } = useValues(broadcastTestSendLogic(props))
    const { setModalOpen } = useActions(broadcastTestSendLogic(props))

    return (
        <div
            className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-surface-primary p-4"
            data-attr="broadcast-review-test-email"
        >
            <div className="flex min-w-0 flex-1 items-start gap-2">
                {lastTestSentTo ? <IconCheckCircle className="mt-0.5 shrink-0 text-success text-lg" /> : null}
                <div className="flex min-w-0 flex-col">
                    <span className="font-semibold">
                        {lastTestSentTo ? `Test sent to ${lastTestSentTo}` : 'Send yourself a test first'}
                    </span>
                    <span className="text-secondary text-xs">
                        {lastTestSentTo
                            ? 'Check it in your inbox, on desktop and mobile, before you send.'
                            : 'Read the email in a real inbox and click its links before it reaches your audience.'}
                    </span>
                </div>
            </div>
            <LemonButton
                type={lastTestSentTo ? 'secondary' : 'primary'}
                icon={<IconSend />}
                onClick={() => setModalOpen(true)}
                data-attr="broadcast-review-send-test"
            >
                {lastTestSentTo ? 'Send another test' : 'Send test email'}
            </LemonButton>
        </div>
    )
}

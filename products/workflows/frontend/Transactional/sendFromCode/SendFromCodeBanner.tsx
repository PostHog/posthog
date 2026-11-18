import { useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonBanner, LemonModal } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { transactionalEmailsLogic } from '../transactionalEmailsLogic'
import { SendFromCodeSetup } from './SendFromCodeSetup'
import { SendingDomainRow } from './SendingDomainRow'

export function SendFromCodeBanner({
    guideOpen,
    onGuideOpenChange,
}: {
    guideOpen: boolean
    onGuideOpenChange: (open: boolean) => void
}): JSX.Element | null {
    const { codeEmails, transactionalTemplatesLoading, transactionalTemplatesFailed } =
        useValues(transactionalEmailsLogic)
    const sendFromCodeEnabled = useFeatureFlag('WORKFLOWS_EMAIL_FROM_CODE')
    const offered =
        sendFromCodeEnabled &&
        codeEmails?.length === 0 &&
        !transactionalTemplatesLoading &&
        !transactionalTemplatesFailed

    if (!offered) {
        return null
    }

    return (
        <>
            <LemonBanner
                type="info"
                // pinned: storage key for the dismissal
                dismissKey="transactional-send-from-code-banner"
                action={{
                    children: 'Show me how',
                    'data-attr': 'send-from-code-show-me-how',
                    onClick: () => {
                        // pinned: analytics event name
                        posthog.capture('send from code guide opened', { surface: 'transactional' })
                        onGuideOpenChange(true)
                    },
                }}
            >
                Your code can send any email with one API call, without designing it in PostHog first. Each one shows up
                in this list with its own metrics.
            </LemonBanner>
            <LemonModal
                isOpen={guideOpen}
                onClose={() => onGuideOpenChange(false)}
                title="Send an email from your code"
                width={720}
            >
                {guideOpen ? (
                    <div className="flex flex-col gap-4">
                        <SendingDomainRow />
                        <SendFromCodeSetup surface="transactional_guide" />
                    </div>
                ) : null}
            </LemonModal>
        </>
    )
}

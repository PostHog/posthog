import posthog from 'posthog-js'
import { useState } from 'react'

import { LemonBanner, LemonModal } from '@posthog/lemon-ui'

import { ProjectSenderSnippet } from './ProjectSenderSnippet'
import { SendingDomainRow } from './SendingDomainRow'

export function SendFromCodeBanner(): JSX.Element {
    const [guideOpen, setGuideOpen] = useState(false)

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
                        setGuideOpen(true)
                    },
                }}
            >
                Your code can send any email with one API call, no template needed. Each one shows up in this list with
                its own metrics.
            </LemonBanner>
            <LemonModal
                isOpen={guideOpen}
                onClose={() => setGuideOpen(false)}
                title="Send an email from your code"
                width={720}
            >
                {guideOpen ? (
                    <div className="flex flex-col gap-4">
                        <SendingDomainRow />
                        <ProjectSenderSnippet surface="transactional_guide" />
                    </div>
                ) : null}
            </LemonModal>
        </>
    )
}

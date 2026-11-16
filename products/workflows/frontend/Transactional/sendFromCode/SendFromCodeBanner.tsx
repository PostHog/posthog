import { useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { LemonBanner, LemonModal } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { transactionalEmailsLogic } from '../transactionalEmailsLogic'
import { SEND_FROM_CODE_GUIDE_PARAM, SEND_FROM_CODE_GUIDE_VALUE } from './sendFromCodeGuideUrl'
import { SendFromCodeSetup } from './SendFromCodeSetup'
import { SendingDomainRow } from './SendingDomainRow'

export function SendFromCodeBanner(): JSX.Element | null {
    const { codeEmails, transactionalTemplatesLoading, transactionalTemplatesFailed } =
        useValues(transactionalEmailsLogic)
    const sendFromCodeEnabled = useFeatureFlag('WORKFLOWS_EMAIL_FROM_CODE')
    const { searchParams } = useValues(router)
    const [guideOpen, setGuideOpen] = useState(false)
    const offered =
        sendFromCodeEnabled &&
        codeEmails?.length === 0 &&
        !transactionalTemplatesLoading &&
        !transactionalTemplatesFailed
    const linkedToGuide = searchParams[SEND_FROM_CODE_GUIDE_PARAM] === SEND_FROM_CODE_GUIDE_VALUE

    useEffect(() => {
        if (!offered || !linkedToGuide) {
            return
        }
        // pinned: analytics event name
        posthog.capture('send from code guide opened', { surface: 'transactional', entry: 'domain_ready' })
        setGuideOpen(true)
        const { [SEND_FROM_CODE_GUIDE_PARAM]: _guide, ...otherParams } = router.values.searchParams
        router.actions.replace(router.values.location.pathname, otherParams, router.values.hashParams)
    }, [offered, linkedToGuide])

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
                        setGuideOpen(true)
                    },
                }}
            >
                Your code can send any email with one API call, without designing it in PostHog first. Each one shows up
                in this list with its own metrics.
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
                        <SendFromCodeSetup surface="transactional_guide" />
                    </div>
                ) : null}
            </LemonModal>
        </>
    )
}

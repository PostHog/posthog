import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { comingSoonInterestLogic } from './comingSoonInterestLogic'
import { ComingSoonInterestModal } from './ComingSoonInterestModal'
import { ComingSoonInterestTag } from './ComingSoonInterestTag'
import { SMTP_INTEREST_SURVEY } from './smtpInterestSurvey'

export function SmtpComingSoonButton(): JSX.Element {
    const logic = comingSoonInterestLogic(SMTP_INTEREST_SURVEY)
    const { hasRecordedInterest } = useValues(logic)
    const { registerInterest } = useActions(logic)

    return (
        <>
            <LemonButton
                type="tertiary"
                size="small"
                sideIcon={<ComingSoonInterestTag hasRecordedInterest={hasRecordedInterest} />}
                tooltip={
                    hasRecordedInterest
                        ? 'You told us you want SMTP. Click to add or change your note.'
                        : 'Coming soon: send email through PostHog from any app or tool that supports SMTP, with no code changes. Click to tell us you want this.'
                }
                onClick={registerInterest}
                data-attr="transactional-smtp-coming-soon"
            >
                SMTP
            </LemonButton>
            <ComingSoonInterestModal
                survey={SMTP_INTEREST_SURVEY}
                title="SMTP is coming soon"
                question="What would you use SMTP for, and what do you use to send these emails today?"
                placeholder="For example, which app or tool would send the email, and what handles it now"
                data-attr="transactional-smtp-coming-soon"
            />
        </>
    )
}

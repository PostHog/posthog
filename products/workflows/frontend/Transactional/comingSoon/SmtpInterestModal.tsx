import { ComingSoonInterestModal } from './ComingSoonInterestModal'
import { SMTP_INTEREST_SURVEY } from './smtpInterestSurvey'
import { useComingSoonInterestSurvey } from './useComingSoonInterestSurvey'

export function SmtpInterestModal(): JSX.Element {
    const survey = useComingSoonInterestSurvey(SMTP_INTEREST_SURVEY)
    return (
        <ComingSoonInterestModal
            survey={survey}
            title="SMTP is coming soon"
            question="What would you use SMTP for, and what do you use to send these emails today?"
            placeholder="For example, which app or tool would send the email, and what handles it now"
            data-attr="transactional-smtp-coming-soon"
        />
    )
}

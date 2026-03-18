import { useValues } from 'kea'

import { IconSupport } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'

import { llmAnalyticsSessionFeedbackLogic } from './llmAnalyticsSessionFeedbackLogic'

function getFeedbackTagType(rating: string): 'success' | 'warning' | 'danger' | 'muted' {
    switch (rating) {
        case 'good':
            return 'success'
        case 'okay':
            return 'warning'
        case 'bad':
            return 'danger'
        default:
            return 'muted'
    }
}

function formatTriggerType(triggerType: string): string {
    switch (triggerType) {
        case 'message_interval':
            return 'Interval'
        case 'random_sample':
            return 'Sample'
        case 'manual':
            return 'Manual'
        case 'retry':
            return 'Retry'
        case 'cancel':
            return 'Cancel'
        default:
            return triggerType
    }
}

interface LLMASessionFeedbackDisplayProps {
    sessionId: string
}

export function LLMASessionFeedbackDisplay({ sessionId }: LLMASessionFeedbackDisplayProps): JSX.Element | null {
    const { sessionFeedback, sessionSupportTickets } = useValues(llmAnalyticsSessionFeedbackLogic({ sessionId }))

    if (sessionFeedback.length === 0 && sessionSupportTickets.length === 0) {
        return null
    }

    return (
        <>
            {sessionFeedback.length > 0 && (
                <>
                    {sessionFeedback.map((feedback: { rating: string; triggerType: string }, index: number) => (
                        <span key={`feedback-group-${index}`} className="contents">
                            <LemonTag
                                size="medium"
                                className="bg-surface-primary"
                                type={getFeedbackTagType(feedback.rating)}
                                title={`Feedback: ${feedback.rating}`}
                            >
                                {feedback.rating === 'implicit_dismiss'
                                    ? 'Dismissed'
                                    : feedback.rating.charAt(0).toUpperCase() + feedback.rating.slice(1)}
                            </LemonTag>
                            <LemonTag
                                size="medium"
                                className="bg-surface-primary"
                                type="muted"
                                title={`Trigger: ${feedback.triggerType}`}
                            >
                                {formatTriggerType(feedback.triggerType)}
                            </LemonTag>
                        </span>
                    ))}
                </>
            )}
            {sessionSupportTickets.length > 0 && (
                <>
                    {sessionSupportTickets.map((ticket: { ticketId: string }, index: number) => (
                        <Link
                            key={`ticket-${index}`}
                            to={`https://posthoghelp.zendesk.com/agent/tickets/${ticket.ticketId}`}
                            target="_blank"
                            className="flex"
                        >
                            <LemonTag
                                size="medium"
                                className="bg-surface-primary"
                                icon={<IconSupport />}
                                title={`Support ticket: ${ticket.ticketId}`}
                            >
                                Ticket
                            </LemonTag>
                        </Link>
                    ))}
                </>
            )}
        </>
    )
}

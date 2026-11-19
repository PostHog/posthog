import { useActions, useValues } from 'kea'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { comingSoonInterestLogic } from './comingSoonInterestLogic'
import { ComingSoonInterestModal } from './ComingSoonInterestModal'
import { ComingSoonInterestTag } from './ComingSoonInterestTag'
import { RECEIVING_INTEREST_SURVEY } from './receivingInterestSurvey'
import { useComingSoonInterestSurvey } from './useComingSoonInterestSurvey'

/** Sending is the only real view, so choosing Receiving asks about interest and leaves Sending selected. */
export function EmailDirectionToggle(): JSX.Element {
    const survey = useComingSoonInterestSurvey(RECEIVING_INTEREST_SURVEY)
    const logic = comingSoonInterestLogic(survey)
    const { hasRecordedInterest } = useValues(logic)
    const { registerInterest } = useActions(logic)

    return (
        <>
            <LemonSegmentedButton
                size="small"
                value="sending"
                onChange={(direction) => {
                    if (direction === 'receiving') {
                        registerInterest()
                    }
                }}
                options={[
                    { value: 'sending', label: 'Sending' },
                    {
                        value: 'receiving',
                        label: (
                            <span className="flex items-center gap-1.5">
                                Receiving
                                <ComingSoonInterestTag hasRecordedInterest={hasRecordedInterest} />
                            </span>
                        ),
                        tooltip: hasRecordedInterest
                            ? 'You asked for receiving email. Click to add or change your note.'
                            : 'Coming soon: receiving email in PostHog, such as replies to what you send, shown in this log. Click to tell us you want this.',
                        'data-attr': 'transactional-receiving-coming-soon',
                    },
                ]}
                className="max-w-full self-start"
            />
            <ComingSoonInterestModal
                survey={survey}
                title="Receiving email is coming soon"
                question="What would you use receiving email for, and what do you use to handle incoming email today?"
                placeholder="For example, which emails you need to receive, and what handles them now"
                data-attr="transactional-receiving-coming-soon"
            />
        </>
    )
}

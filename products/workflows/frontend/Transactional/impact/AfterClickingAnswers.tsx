import { LemonTag, Link } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { VERDICT_LABEL } from 'products/replay_vision/frontend/utils/observation'

import { AfterClickingNotice } from './AfterClickingNotice'
import { SCAN_QUESTION, type SessionAnswer } from './afterClickingScanLogic'

export function AfterClickingAnswers({
    answers,
    withoutAnswer,
}: {
    answers: SessionAnswer[]
    withoutAnswer: number
}): JSX.Element {
    return (
        <AfterClickingNotice title={SCAN_QUESTION}>
            {answers.map(({ sessionId, verdict, reasoning }) => (
                <div key={sessionId} className="flex flex-col gap-1 items-start border-t pt-2 w-full">
                    <LemonTag type={verdict === 'yes' ? 'highlight' : 'muted'}>{VERDICT_LABEL[verdict]}</LemonTag>
                    <span className="text-secondary text-sm whitespace-pre-wrap">{reasoning}</span>
                    <Link to={urls.replaySingle(sessionId)} className="text-sm" data-attr="email-impact-open-session">
                        Watch session
                    </Link>
                </div>
            ))}
            {withoutAnswer > 0 && (
                <span className="text-secondary text-sm">
                    {pluralize(withoutAnswer, 'session', 'sessions')} {withoutAnswer === 1 ? 'has' : 'have'} no answer.
                </span>
            )}
        </AfterClickingNotice>
    )
}

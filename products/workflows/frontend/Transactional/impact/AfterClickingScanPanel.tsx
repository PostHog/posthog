import { useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton, LemonTag, Link } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { VERDICT_LABEL } from 'products/replay_vision/frontend/utils/observation'

import { AfterClickingNotice } from './AfterClickingNotice'
import { SCAN_QUESTION, afterClickingScanLogic, scanDisabledReason } from './afterClickingScanLogic'

export function AfterClickingScanPanel(): JSX.Element {
    const { scanState: state, currentTeam } = useValues(afterClickingScanLogic)
    const { loadSessions, scanSessions } = useActions(afterClickingScanLogic)
    const scanButton = (label: string): JSX.Element => (
        <LemonButton
            type="primary"
            size="small"
            onClick={() => scanSessions()}
            disabledReason={scanDisabledReason(currentTeam)}
            data-attr="email-impact-scan"
        >
            {label}
        </LemonButton>
    )

    switch (state.kind) {
        case 'loading-sessions':
            return <LemonSkeleton className="h-24" />
        case 'sessions-error':
            return (
                <AfterClickingNotice title="The sessions from this email couldn't load">
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => loadSessions()}
                        data-attr="email-impact-sessions-retry"
                    >
                        Try again
                    </LemonButton>
                </AfterClickingNotice>
            )
        case 'no-sessions':
            return (
                <AfterClickingNotice title="No sessions yet">
                    <span className="text-secondary text-sm">No sessions started from this email in this period.</span>
                </AfterClickingNotice>
            )
        case 'ready':
            return (
                <AfterClickingNotice title="Ask Replay vision about these sessions">
                    <span className="text-secondary text-sm">
                        Replay vision watches {state.hasMore ? `${state.sessionCount} of the` : 'the'}{' '}
                        {pluralize(state.sessionCount, 'session', 'sessions', !state.hasMore)} people started from this
                        email and answers one question for each: {SCAN_QUESTION} Each session it scans uses Replay
                        vision credits.
                    </span>
                    {scanButton('Scan sessions')}
                </AfterClickingNotice>
            )
        case 'scanning':
            return (
                <AfterClickingNotice title="Scanning sessions">
                    <LemonProgress
                        className="self-stretch"
                        percent={state.total ? (state.done / state.total) * 100 : 0}
                    />
                    <span className="text-secondary text-sm">
                        {`${state.done} of ${pluralize(state.total, 'session', 'sessions')} scanned`}
                    </span>
                </AfterClickingNotice>
            )
        case 'finished':
            return (
                <AfterClickingNotice title={SCAN_QUESTION}>
                    {state.answers.map(({ sessionId, verdict, reasoning }) => (
                        <div key={sessionId} className="flex flex-col gap-1 items-start border-t pt-2 w-full">
                            <LemonTag type={verdict === 'yes' ? 'highlight' : 'muted'}>
                                {VERDICT_LABEL[verdict]}
                            </LemonTag>
                            <span className="text-secondary text-sm whitespace-pre-wrap">{reasoning}</span>
                            <Link to={urls.replaySingle(sessionId)} className="text-sm" data-attr="email-impact-watch">
                                Watch session
                            </Link>
                        </div>
                    ))}
                    {state.withoutAnswer > 0 && (
                        <span className="text-secondary text-sm">
                            {`${pluralize(state.withoutAnswer, 'session', 'sessions')} ${state.withoutAnswer === 1 ? 'has' : 'have'} no answer.`}
                        </span>
                    )}
                </AfterClickingNotice>
            )
        case 'scan-error':
            return (
                <AfterClickingNotice title="The scan didn't finish">
                    <span className="text-secondary text-sm">{state.message}</span>
                    {scanButton('Try again')}
                </AfterClickingNotice>
            )
    }
}

import { useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { pluralize } from 'lib/utils/strings'

import { AfterClickingAnswers } from './AfterClickingAnswers'
import { AfterClickingNotice } from './AfterClickingNotice'
import { SCAN_QUESTION, afterClickingScanLogic } from './afterClickingScanLogic'

export function AfterClickingScanPanel(): JSX.Element {
    const { scanState: state } = useValues(afterClickingScanLogic)
    const { loadSessions, startScan } = useActions(afterClickingScanLogic)
    const scanButton = (label: string): JSX.Element => (
        <LemonButton type="primary" size="small" onClick={() => startScan()} data-attr="email-impact-scan">
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
                    <span className="text-secondary text-sm">
                        Replay vision scans the sessions people start by clicking a link in this email. None started in
                        this period.
                    </span>
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
                        <span>{state.done}</span> of <span>{state.total}</span>{' '}
                        {pluralize(state.total, 'session', 'sessions', false)} scanned
                    </span>
                </AfterClickingNotice>
            )
        case 'finished':
            return <AfterClickingAnswers answers={state.answers} withoutAnswer={state.withoutAnswer} />
        case 'scan-error':
            return (
                <AfterClickingNotice title="The scan didn't finish">
                    <span className="text-secondary text-sm">{state.message}</span>
                    {scanButton('Scan again')}
                </AfterClickingNotice>
            )
    }
}

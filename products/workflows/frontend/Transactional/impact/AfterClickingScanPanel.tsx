import { useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { pluralize } from 'lib/utils/strings'

import { AfterClickingBlockedNotice } from './AfterClickingBlockedNotice'
import { AfterClickingNotice } from './AfterClickingNotice'
import { AfterClickingQuestionPicker } from './AfterClickingQuestionPicker'
import { afterClickingScanLogic, isScanBlocked, isScanOutcome } from './afterClickingScanLogic'
import { AfterClickingScanOutcome } from './AfterClickingScanOutcome'
import { AfterClickingSkippedSessions } from './AfterClickingSkippedSessions'

export function AfterClickingScanPanel(): JSX.Element {
    const { scanState: state } = useValues(afterClickingScanLogic)
    const { loadSessions } = useActions(afterClickingScanLogic)

    if (isScanBlocked(state)) {
        return <AfterClickingBlockedNotice state={state} />
    }
    if (isScanOutcome(state)) {
        return <AfterClickingScanOutcome state={state} />
    }
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
        case 'questions':
            return <AfterClickingQuestionPicker sessionCount={state.sessionCount} hasMore={state.hasMore} />
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
                    <AfterClickingSkippedSessions skipped={state.skipped} />
                </AfterClickingNotice>
            )
    }
}

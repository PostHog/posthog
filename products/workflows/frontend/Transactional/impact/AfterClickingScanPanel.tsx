import { useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { AfterClickingNotice } from './AfterClickingNotice'
import { AfterClickingQuestionPicker } from './AfterClickingQuestionPicker'
import { afterClickingScanLogic } from './afterClickingScanLogic'

export function AfterClickingScanPanel(): JSX.Element {
    const { scanState: state } = useValues(afterClickingScanLogic)
    const { loadSessions, retryScan, resetScan } = useActions(afterClickingScanLogic)
    const askAnother = (
        <LemonButton type="secondary" size="small" onClick={resetScan} data-attr="email-impact-ask-another-question">
            Ask another question
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
                        {state.done} of {pluralize(state.total, 'session')} scanned
                    </span>
                </AfterClickingNotice>
            )
        case 'finished':
            return (
                <AfterClickingNotice title="Scan finished">
                    <span className="text-secondary text-sm">
                        {state.withResult} of {pluralize(state.total, 'session')} have an answer.
                    </span>
                    {askAnother}
                </AfterClickingNotice>
            )
        case 'credits-used-up':
            return (
                <AfterClickingNotice title="Replay vision credits are used up">
                    <span className="text-secondary text-sm">
                        Your organization has used its Replay vision credits for this period, so no sessions were
                        scanned.
                    </span>
                    <div className="flex flex-wrap gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            to={urls.organizationBilling()}
                            data-attr="email-impact-open-billing"
                        >
                            Open billing
                        </LemonButton>
                        {askAnother}
                    </div>
                </AfterClickingNotice>
            )
        case 'ai-analysis-not-allowed':
            return (
                <AfterClickingNotice title="AI analysis is off for this organization">
                    <span className="text-secondary text-sm">
                        Replay vision sends recordings to an AI provider to answer questions. An organization admin or
                        owner can allow AI analysis in settings.
                    </span>
                    <div className="flex flex-wrap gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            to={urls.settings('organization-details', 'organization-ai-consent')}
                            data-attr="email-impact-allow-ai-analysis"
                        >
                            Open AI settings
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={retryScan}
                            data-attr="email-impact-scan-retry"
                        >
                            Try again
                        </LemonButton>
                    </div>
                </AfterClickingNotice>
            )
        case 'scan-error':
            return (
                <AfterClickingNotice title="The scan didn't finish">
                    <span className="text-secondary text-sm">{state.message}</span>
                    <div className="flex flex-wrap gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={retryScan}
                            data-attr="email-impact-scan-retry"
                        >
                            Try again
                        </LemonButton>
                        {askAnother}
                    </div>
                </AfterClickingNotice>
            )
    }
}

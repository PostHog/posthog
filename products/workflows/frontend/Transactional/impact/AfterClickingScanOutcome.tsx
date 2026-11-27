import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { AfterClickingNotice } from './AfterClickingNotice'
import { afterClickingScanLogic, type ScanOutcomeState } from './afterClickingScanLogic'
import { AfterClickingSkippedSessions } from './AfterClickingSkippedSessions'

export function AfterClickingScanOutcome({ state }: { state: ScanOutcomeState }): JSX.Element {
    const { retryScan, resetScan } = useActions(afterClickingScanLogic)
    const askAnother = (
        <LemonButton type="secondary" size="small" onClick={resetScan} data-attr="email-impact-ask-another-question">
            Ask another question
        </LemonButton>
    )

    switch (state.kind) {
        case 'finished':
            return (
                <AfterClickingNotice title="Scan finished">
                    <span className="text-secondary text-sm">
                        <span>{state.withResult}</span> of <span>{state.scanned}</span> scanned{' '}
                        {pluralize(state.scanned, 'session', 'sessions', false)} have an answer.
                    </span>
                    <AfterClickingSkippedSessions skipped={state.skipped} />
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

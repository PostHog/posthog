import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { pullRequestsLogic } from '../../logics/pullRequestsLogic'

export function MonitorPullRequest(): JSX.Element | null {
    const { selectedPR, note, monitoringRequestLoading, monitorError } = useValues(pullRequestsLogic)
    const { setNote, monitorPR } = useActions(pullRequestsLogic)
    if (!selectedPR || selectedPR.report) {
        return null
    }
    if (selectedPR.state === 'closed') {
        return (
            <div className="p-5">
                <LemonBanner type="info">
                    This PR was closed without merging, so its impact cannot be monitored.
                </LemonBanner>
            </div>
        )
    }
    return (
        <div className="p-5 border-b border-primary flex flex-col gap-3">
            <div>
                <h3 className="text-sm font-semibold mb-1">Monitor this PR's impact</h3>
                <p className="text-secondary mb-0">
                    An agent will inspect the PR, choose a key metric, and create a report assigned to you. Monitoring
                    begins after merge.
                </p>
            </div>
            <label className="flex flex-col gap-1">
                <span className="text-sm font-medium">
                    What should we watch? <span className="font-normal text-secondary">(optional)</span>
                </span>
                <LemonTextArea
                    value={note}
                    onChange={setNote}
                    maxLength={4000}
                    rows={2}
                    placeholder="For example, checkout completion for new users"
                    disabled={monitoringRequestLoading}
                />
            </label>
            {monitorError && <LemonBanner type="error">{monitorError}</LemonBanner>}
            <LemonButton
                className="self-start"
                type="primary"
                onClick={() => monitorPR()}
                loading={monitoringRequestLoading}
            >
                Monitor PR
            </LemonButton>
        </div>
    )
}

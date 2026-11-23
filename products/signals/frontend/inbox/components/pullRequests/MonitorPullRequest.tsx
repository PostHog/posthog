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
            <LemonBanner type="info">
                This pull request was closed without merging, so its impact cannot be monitored.
            </LemonBanner>
        )
    }
    return (
        <div className="flex flex-col gap-2.5">
            <p className="m-0 text-xs text-secondary">
                An agent will inspect this pull request, choose a key metric, and create a report for you.{' '}
                {selectedPR.state === 'merged'
                    ? 'Monitoring starts from its merge time.'
                    : 'Monitoring starts once it merges.'}
            </p>
            <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-secondary">
                    What should we watch? <span className="font-normal text-tertiary">(optional)</span>
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
            {monitorError ? <LemonBanner type="error">{monitorError}</LemonBanner> : null}
            <LemonButton
                className="self-start"
                size="small"
                type="primary"
                data-attr="inbox-pr-monitor-submit"
                onClick={() => monitorPR()}
                loading={monitoringRequestLoading}
            >
                Monitor PR
            </LemonButton>
        </div>
    )
}

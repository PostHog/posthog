import { useActions, useValues } from 'kea'

import { LemonBanner, LemonModal, LemonTag, LemonTagType, Spinner, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'
import { tryDecodeURIComponent } from 'lib/utils/url'

import { JourneyStep, JourneyTransition, agentAnalyticsLogic } from './agentAnalyticsLogic'
import { AgentQueryError } from './AgentQueryError'

const TRANSITION_CONFIG: Record<JourneyTransition, { label: string; help: string }> = {
    start: { label: 'First request', help: 'The first request observed in this journey.' },
    confirmed: {
        label: 'Followed a link',
        help: 'The referrer points to the previous page, so this request followed a link from it.',
    },
    sequential: {
        label: 'Next request',
        help: 'This request came after the previous one in time. There is no referrer linking them.',
    },
    parallel: {
        label: 'Simultaneous',
        help: 'This request shares a timestamp with the previous one, so their order is ambiguous.',
    },
}

const statusTagType = (status: number): LemonTagType => {
    if (status >= 500) {
        return 'danger'
    }
    if (status >= 400) {
        return 'warning'
    }
    if (status >= 300) {
        return 'caution'
    }
    return 'success'
}

const offsetLabel = (step: JourneyStep, firstTimestamp: string | null): string => {
    if (!step.timestamp || !firstTimestamp) {
        return ''
    }
    const seconds = dayjs(step.timestamp).diff(dayjs(firstTimestamp), 'second')
    if (seconds <= 0) {
        return 'start'
    }
    return `+${humanFriendlyDuration(seconds, { maxUnits: 2 })}`
}

const JourneyStepRow = ({
    step,
    firstTimestamp,
}: {
    step: JourneyStep
    firstTimestamp: string | null
}): JSX.Element => {
    const transition = TRANSITION_CONFIG[step.transition]
    return (
        <li className="flex gap-3">
            <span className="w-16 shrink-0 pt-0.5 text-right text-xs tabular-nums text-tertiary">
                {offsetLabel(step, firstTimestamp)}
            </span>
            <div className="flex min-w-0 flex-col gap-1 border-l border-primary pb-4 pl-3">
                <span className="truncate font-medium">{tryDecodeURIComponent(step.path) || '/'}</span>
                <div className="flex flex-wrap items-center gap-2 text-xs">
                    <LemonTag type={statusTagType(step.status)} size="small">
                        {step.status || 'No status'}
                    </LemonTag>
                    <span className="text-secondary">{step.format === 'markdown' ? 'Markdown' : 'HTML'}</span>
                    <Tooltip title={transition.help}>
                        <span className="text-tertiary">· {transition.label}</span>
                    </Tooltip>
                </div>
            </div>
        </li>
    )
}

export const AgentJourneyDetail = (): JSX.Element => {
    const { selectedJourney, selectedJourneyKey, journeyDetail, journeyDetailLoading, journeyDetailError } =
        useValues(agentAnalyticsLogic)
    const { setSelectedJourneyKey, loadJourneyDetail } = useActions(agentAnalyticsLogic)

    const firstTimestamp = journeyDetail[0]?.timestamp ?? null

    return (
        <LemonModal
            isOpen={selectedJourneyKey !== null}
            onClose={() => setSelectedJourneyKey(null)}
            title="Journey timeline"
            description={
                selectedJourney ? (
                    <span className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-default">{selectedJourney.agent}</span>
                        <span className="text-secondary">on {selectedJourney.host || 'unknown domain'}</span>
                        {selectedJourney.started ? (
                            <span className="text-secondary">
                                started <TZLabel time={selectedJourney.started} />
                            </span>
                        ) : null}
                    </span>
                ) : (
                    'This request sequence is ordered by time, not proven to be one conversation.'
                )
            }
            width={640}
        >
            <AgentQueryError
                error={journeyDetailError}
                subject="this journey"
                onRetry={loadJourneyDetail}
                loading={journeyDetailLoading}
            >
                {journeyDetailLoading && journeyDetail.length === 0 ? (
                    <div className="flex min-h-32 items-center justify-center">
                        <Spinner />
                    </div>
                ) : journeyDetail.length === 0 ? (
                    <p className="text-secondary">No requests were found for this journey in this range.</p>
                ) : (
                    <>
                        <ol className="m-0 flex list-none flex-col p-0">
                            {journeyDetail.map((step, index) => (
                                <JourneyStepRow
                                    key={`${step.path}-${index}`}
                                    step={step}
                                    firstTimestamp={firstTimestamp}
                                />
                            ))}
                        </ol>
                        {selectedJourney && selectedJourney.requests > journeyDetail.length ? (
                            <LemonBanner type="info">
                                Showing the first {humanFriendlyLargeNumber(journeyDetail.length)} of{' '}
                                {humanFriendlyLargeNumber(selectedJourney.requests)} requests in this journey.
                            </LemonBanner>
                        ) : null}
                    </>
                )}
            </AgentQueryError>
        </LemonModal>
    )
}

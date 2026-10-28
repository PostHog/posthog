import { IconCheckCircle, IconClock, IconHourglass, IconInfo, IconLetter, IconWarning } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { ReadonlyRunSurface } from 'products/posthog_ai/frontend/api/readableRun'

import type { FirstReportProgressState } from '../../logics/inboxSetupLogic'
import { RunStatusIndicator } from '../cards/runStatusVariant'
import { InboxReportPreview } from '../onboarding/InboxReportPreview'

export interface FirstReportProgressProps {
    result: FirstReportProgressState
    notificationEmail?: string | null
}

function FirstReportStatusGlyph({ status }: { status: FirstReportProgressState['status'] }): JSX.Element {
    switch (status) {
        case 'pending':
            return <RunStatusIndicator variant="queued" showLabel={false} />
        case 'running':
            return <RunStatusIndicator variant="live" showLabel={false} />
        case 'no_actionable_finding':
            return <IconCheckCircle className="shrink-0 text-lg text-success" />
        case 'incomplete':
            return <IconWarning className="shrink-0 text-lg text-warning" />
        case 'insufficient_data':
            return <IconInfo className="shrink-0 text-lg text-secondary" />
        case 'no_data':
            return <IconHourglass className="shrink-0 text-lg text-secondary" />
    }
}

export function FirstReportProgress({ result, notificationEmail }: FirstReportProgressProps): JSX.Element {
    const messages = {
        pending: ['Checking your project', 'We’re checking which data is available for your first investigation.'],
        running: ['Looking for your first report', 'We’re checking your project for an issue you can act on.'],
        no_data: ['Waiting for your first report', 'Your setup is ready. There isn’t any data to investigate yet.'],
        insufficient_data: [
            'More data is needed',
            'The investigation finished, but there isn’t enough data yet to produce a reliable report.',
        ],
        no_actionable_finding: [
            'Your first investigation is complete',
            'We checked your data and didn’t find anything worth reporting yet.',
        ],
        incomplete: [
            'Your first investigation couldn’t finish',
            'We couldn’t complete the investigation. This does not mean your project has no data. Review your connections and the investigation activity, if available.',
        ],
    }
    const [title, description] = messages[result.status]
    const isLive = result.status === 'pending' || result.status === 'running'

    return (
        <div className="@container w-full min-w-0">
            <div className="grid overflow-hidden rounded border border-primary bg-surface-primary @min-[48rem]:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
                <div className="flex min-w-0 flex-col gap-3 border-b border-primary p-5 @min-[48rem]:border-r @min-[48rem]:border-b-0">
                    <div className="flex items-center gap-2.5">
                        <FirstReportStatusGlyph status={result.status} />
                        <h2 className="m-0 text-base font-semibold leading-snug">{title}</h2>
                    </div>
                    <p className="m-0 text-sm text-secondary">
                        <span>{description}</span>
                        {result.status === 'running' && (
                            <span>
                                {' '}
                                This takes <strong>roughly 2½ minutes</strong>.
                            </span>
                        )}
                    </p>
                    {result.status === 'insufficient_data' && result.missing_data?.length ? (
                        <ul className="m-0 text-sm text-secondary">
                            {result.missing_data.map((item, index) => (
                                <li key={index}>{item}</li>
                            ))}
                        </ul>
                    ) : null}
                    {result.started_at || notificationEmail ? (
                        <div className="mt-auto flex flex-col gap-1.5 pt-1 text-xs text-tertiary">
                            {result.started_at ? (
                                <span className="flex items-center gap-1.5">
                                    <IconClock className="size-3.5 shrink-0" />
                                    <span>
                                        Started <TZLabel time={result.started_at} />
                                    </span>
                                </span>
                            ) : null}
                            {notificationEmail ? (
                                <span className="flex items-center gap-1.5">
                                    <IconLetter className="size-3.5 shrink-0" />
                                    <span>We’ll notify you when your first report is ready.</span>
                                </span>
                            ) : null}
                        </div>
                    ) : null}
                    {result.status === 'incomplete' ? (
                        <div className="flex flex-wrap gap-2">
                            <LemonButton type="secondary" size="small" to={urls.inbox('settings')}>
                                Review connections
                            </LemonButton>
                        </div>
                    ) : null}
                </div>
                <div className="flex min-w-0 flex-col bg-surface-secondary">
                    {result.task_id && result.task_run_id ? (
                        // The viewer's virtualized thread owns scroll, so this box only bounds the height and clips.
                        <section
                            className="h-96 min-h-0 overflow-hidden"
                            aria-label="First report investigation activity"
                        >
                            <ReadonlyRunSurface
                                taskId={result.task_id}
                                runId={result.task_run_id}
                                interaction="live"
                                threadRowClassName="px-4"
                                threadListClassName="py-3"
                            />
                        </section>
                    ) : result.status === 'no_data' ? (
                        <section className="flex min-w-0 flex-col gap-3 p-5" aria-label="Example report">
                            <h3 className="m-0 text-sm font-semibold">Example report</h3>
                            <InboxReportPreview mode="waiting-for-data" />
                        </section>
                    ) : isLive ? (
                        <span
                            className="flex h-96 items-center justify-center gap-2 p-5 text-sm text-secondary"
                            role="status"
                        >
                            <Spinner className="text-lg" />
                            <span>
                                {result.status === 'pending'
                                    ? 'Checking available data…'
                                    : 'Starting the investigation…'}
                            </span>
                        </span>
                    ) : (
                        <p className="m-0 p-5 text-sm text-secondary">No investigation activity is available.</p>
                    )}
                </div>
            </div>
        </div>
    )
}

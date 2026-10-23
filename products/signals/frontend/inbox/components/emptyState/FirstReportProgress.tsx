import { Link, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { ReadonlyRunSurface } from 'products/posthog_ai/frontend/api/readableRun'

import { FirstReportStateApi } from '../../../generated/api.schemas'
import { RunLogContainer } from '../detail/RunLogContainer'
import { InboxReportPreview } from '../onboarding/InboxReportPreview'

export interface FirstReportProgressProps {
    result: FirstReportStateApi
    notificationEmail?: string | null
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
        report_created: [
            'Your first report is ready',
            'Open your inbox to see the finding and its recommended next step.',
        ],
    }
    const [title, description] = messages[result.status]

    return (
        <div className="@container w-full min-w-0">
            <div className="grid items-start gap-6 @min-[48rem]:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
                <div className="flex min-w-0 flex-col gap-3">
                    <h2 className="m-0 text-lg font-semibold">{title}</h2>
                    <p className="m-0 text-sm text-secondary">
                        <span>{description}</span>
                        {result.status === 'running' && (
                            <span>
                                {' '}
                                This takes <strong>roughly 2½ minutes</strong>.
                            </span>
                        )}
                        {notificationEmail && result.status !== 'report_created' && (
                            <span> We’ll notify you when your first report is ready.</span>
                        )}
                    </p>
                    {result.status === 'insufficient_data' && result.missing_data?.length ? (
                        <ul className="m-0 text-sm text-secondary">
                            {result.missing_data.map((item, index) => (
                                <li key={index}>{item}</li>
                            ))}
                        </ul>
                    ) : null}
                    {result.status === 'incomplete' ? (
                        <Link to={urls.inbox('settings')}>Review connections</Link>
                    ) : null}
                    {result.report_id ? (
                        <Link to={urls.inboxReport('reports', result.report_id)}>Open your first report</Link>
                    ) : null}
                </div>
                {result.task_id && result.task_run_id ? (
                    <div
                        className="flex w-full min-w-0 flex-col gap-3"
                        aria-label="First report investigation activity"
                    >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <h3 className="m-0 text-sm font-semibold">Investigation progress</h3>
                            {result.started_at && (
                                <span className="text-xs text-tertiary">
                                    Started <TZLabel time={result.started_at} />
                                </span>
                            )}
                        </div>
                        <RunLogContainer>
                            <ReadonlyRunSurface
                                taskId={result.task_id}
                                runId={result.task_run_id}
                                interaction="live"
                                threadRowClassName="px-3"
                                threadListClassName="py-3"
                            />
                        </RunLogContainer>
                    </div>
                ) : result.status === 'no_data' ? (
                    <div className="flex min-w-0 flex-col gap-3" aria-label="Example report">
                        <h3 className="m-0 text-sm font-semibold">Example report</h3>
                        <InboxReportPreview mode="waiting-for-data" />
                    </div>
                ) : result.status === 'pending' || result.status === 'running' ? (
                    <span className="flex items-center gap-2 text-sm text-secondary" role="status">
                        <Spinner className="text-lg" />
                        <span>
                            {result.status === 'pending' ? 'Checking available data…' : 'Starting the investigation…'}
                        </span>
                    </span>
                ) : (
                    <p className="m-0 text-sm text-secondary">No investigation activity is available.</p>
                )}
            </div>
        </div>
    )
}

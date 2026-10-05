import { IconDownload, IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCollapse, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import type { ScoutTrialsViewProps } from './ScoutTrialsView'
import { ScoutTrialRow, trialIsActive, trialTaskIsActive } from './scoutTrialUtils'

export function ScoutTrialRunHistory(props: ScoutTrialsViewProps): JSX.Element {
    const { rows, selectedConfigId } = props
    return (
        <LemonCollapse
            panels={[
                {
                    key: 'run-history',
                    header: 'Individual run history',
                    content: (
                        <div className="flex flex-col gap-3 border-t pt-4">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                                <h3 className="m-0 text-base">Recent executions</h3>
                                <div className="flex flex-wrap gap-2">
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        icon={<IconRefresh />}
                                        loading={props.refreshing || props.historyLoading}
                                        onClick={() => {
                                            props.refreshResults(true)
                                            props.loadHistory(selectedConfigId!)
                                            props.loadComparisonHistory(selectedConfigId!)
                                        }}
                                    >
                                        Refresh
                                    </LemonButton>
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        icon={<IconDownload />}
                                        onClick={props.downloadResults}
                                        disabledReason={
                                            !rows.some((row) => row.result) ? 'No results have loaded yet.' : undefined
                                        }
                                    >
                                        Download results
                                    </LemonButton>
                                </div>
                            </div>
                            {props.pollError && <LemonBanner type="warning">{props.pollError}</LemonBanner>}
                            <LemonTable<ScoutTrialRow>
                                dataSource={rows}
                                rowKey="launchId"
                                tableLayout="fixed"
                                size="small"
                                loading={props.historyLoading && !rows.length}
                                emptyState="No trial runs yet. Start a trial to compare versions."
                                columns={[
                                    {
                                        title: 'Run',
                                        width: '50%',
                                        render: (_, row) => (
                                            <div className="min-w-0">
                                                <strong className="break-words">{row.variant}</strong>
                                                <div className="text-xs text-muted break-all">
                                                    {row.model ? `${row.model} · ${row.effort}` : row.launchId}
                                                </div>
                                                {row.startedAt && (
                                                    <div className="text-xs text-muted">
                                                        {dayjs(row.startedAt).format('MMM D, HH:mm')}
                                                    </div>
                                                )}
                                                {row.error && (
                                                    <div className="text-xs text-danger break-words">{row.error}</div>
                                                )}
                                            </div>
                                        ),
                                    },
                                    {
                                        title: 'Status',
                                        width: '27%',
                                        render: (_, row) => (
                                            <div className="flex flex-col items-start gap-1">
                                                <LemonTag
                                                    type={
                                                        row.status === 'completed'
                                                            ? 'success'
                                                            : row.status === 'failed'
                                                              ? 'danger'
                                                              : trialIsActive(row.status)
                                                                ? 'primary'
                                                                : 'muted'
                                                    }
                                                    wrap
                                                >
                                                    {row.status.replaceAll('_', ' ')}
                                                </LemonTag>
                                                {row.result && (
                                                    <>
                                                        <span className="text-xs">{`${row.result.reports.length} ${row.result.reports.length === 1 ? 'report' : 'reports'}`}</span>
                                                        <span className="text-xs text-muted">
                                                            {row.result.cost_usd === null
                                                                ? 'Cost unknown'
                                                                : `$${row.result.cost_usd.toFixed(2)}`}
                                                        </span>
                                                    </>
                                                )}
                                            </div>
                                        ),
                                    },
                                    {
                                        title: '',
                                        width: '23%',
                                        render: (_, row) => (
                                            <div className="flex flex-col items-start gap-1">
                                                <LemonButton
                                                    size="xsmall"
                                                    type="tertiary"
                                                    onClick={() => props.selectResult(row.launchId)}
                                                    disabledReason={
                                                        !row.result ? 'Results have not loaded yet.' : undefined
                                                    }
                                                >
                                                    Results
                                                </LemonButton>
                                                {row.result?.task_id &&
                                                    row.result.task_run_id &&
                                                    (trialIsActive(row.status) ||
                                                        trialTaskIsActive(row.result.task_status)) && (
                                                        <LemonButton
                                                            size="xsmall"
                                                            type="tertiary"
                                                            status="danger"
                                                            loading={props.canceling.includes(row.launchId)}
                                                            onClick={() => props.cancelRun(row.launchId)}
                                                        >
                                                            Stop run
                                                        </LemonButton>
                                                    )}
                                            </div>
                                        ),
                                    },
                                ]}
                            />
                            {props.history?.has_more && (
                                <p className="text-xs text-muted m-0">
                                    Showing your 30 most recent runs, plus runs started in this browser.
                                </p>
                            )}
                            <p className="text-xs text-muted m-0">
                                Each row is one scout execution. This history includes older runs and runs from other
                                trials. Select a trial to see its grouped judging report.
                            </p>
                        </div>
                    ),
                },
            ]}
        />
    )
}

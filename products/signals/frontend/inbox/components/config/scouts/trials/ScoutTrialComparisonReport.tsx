import { useState } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCollapse, LemonSwitch, LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { pluralize } from 'lib/utils/strings'

import type { TrialComparisonReportApi } from 'products/signals/frontend/generated/api.schemas'

import { formatRunCost, formatRunDuration } from '../../../../utils/scoutRunsWindow'
import { ScoutRubricReference } from '../ScoutRubricReference'
import {
    TrialCheckRow,
    TrialVersionResult,
    trialCheckRows,
    trialRunVerdictCounts,
    trialVersionResults,
} from './scoutTrialPresentation'
import { ScoutTrialRow, trialPercentage } from './scoutTrialUtils'

export function ScoutTrialComparisonReport({
    report,
    rows = [],
    onSelectRun,
}: {
    report: TrialComparisonReportApi
    rows?: ScoutTrialRow[]
    onSelectRun?: (launchId: string) => void
}): JSX.Element {
    const [filter, setFilter] = useState<{ evaluationId: string; differencesOnly: boolean } | null>(null)
    const versions = trialVersionResults(report, rows)
    const checks = trialCheckRows(report.criteria, versions)
    const differingChecks = checks.filter((check) => check.differs)
    const differencesOnly = filter?.evaluationId === report.evaluation_id ? filter.differencesOnly : checks.length > 5
    const rubricLabel = 'Saved rubric'
    const outcome = report.outcome
    const bestVersionNames = versions
        .filter(({ variant }) => outcome?.variant_ids?.includes(variant.variant_id))
        .map(({ variant }) => variant.label)
        .join(', ')

    return (
        <div className="@container flex min-w-0 flex-col gap-6">
            <LemonBanner
                type={outcome?.status === 'winner' ? 'success' : outcome?.status === 'tie' ? 'info' : 'warning'}
            >
                <div className="flex min-w-0 flex-col gap-1">
                    <strong className="break-words">
                        {outcome?.status === 'winner'
                            ? `Best in this trial: ${bestVersionNames}`
                            : outcome?.status === 'tie'
                              ? `Tie: ${bestVersionNames}`
                              : 'No clear winner'}
                    </strong>
                    <span className="break-words">
                        {outcome?.summary ??
                            'This saved report has no comparison conclusion. Review the results below.'}
                    </span>
                    {outcome?.status === 'inconclusive' && <span>The ranking below is for reference only.</span>}
                </div>
            </LemonBanner>

            <section className="flex min-w-0 flex-col gap-2">
                <h3 className="m-0 text-sm font-semibold">Leaderboard</h3>
                <p className="m-0 text-xs text-muted">Ranked by checks passed. Cost and time don't affect the rank.</p>
                <LemonTable<TrialVersionResult>
                    dataSource={versions}
                    rowKey={({ variant }) => variant.variant_id}
                    size="small"
                    rowClassName={({ variant }) =>
                        outcome?.status === 'winner' && outcome.variant_ids?.includes(variant.variant_id)
                            ? 'bg-success-highlight'
                            : null
                    }
                    columns={[
                        { title: '#', key: 'rank', width: 44, render: (_, version) => version.rank },
                        {
                            title: 'Version',
                            key: 'version',
                            width: 240,
                            render: (_, { variant, letter, settings, prompt }) => (
                                <div className="flex min-w-48 flex-col items-start gap-1">
                                    <div className="flex flex-wrap items-center gap-2">
                                        <LemonTag type="muted">{letter}</LemonTag>
                                        <strong className="break-words">{variant.label}</strong>
                                    </div>
                                    <div className="flex flex-wrap gap-1">
                                        {variant.is_baseline && <LemonTag type="muted">Baseline</LemonTag>}
                                        {outcome?.variant_ids?.includes(variant.variant_id) &&
                                            outcome.status !== 'inconclusive' && (
                                                <LemonTag type={outcome.status === 'winner' ? 'success' : 'muted'} wrap>
                                                    {outcome.status === 'winner' ? 'Most checks passed' : 'Tied'}
                                                </LemonTag>
                                            )}
                                    </div>
                                    {settings.map((setting) => (
                                        <span key={setting} className="text-xs text-muted">
                                            {setting}
                                        </span>
                                    ))}
                                    <span className="text-xs text-muted">{prompt}</span>
                                </div>
                            ),
                        },
                        {
                            title: 'Checks passed',
                            key: 'checks',
                            width: 120,
                            render: (_, { counts }) => (
                                <div className="flex min-w-24 flex-col gap-1">
                                    <strong>{`${counts.passed} / ${counts.passed + counts.failed}`}</strong>
                                    {counts.unknown > 0 && (
                                        <span className="text-xs text-warning">{`${counts.unknown} unknown`}</span>
                                    )}
                                </div>
                            ),
                        },
                        {
                            title: 'Pass rate',
                            key: 'rate',
                            width: 100,
                            render: (_, { variant }) => (
                                <div className="flex min-w-20 flex-col gap-2">
                                    <span>{trialPercentage(variant.score)}</span>
                                    {variant.score !== null && (
                                        <LemonProgress percent={variant.score * 100} strokeColor="var(--success)" />
                                    )}
                                </div>
                            ),
                        },
                        {
                            title: 'Runs judged',
                            key: 'runs',
                            width: 125,
                            render: (_, { variant }) => (
                                <div className="flex min-w-24 flex-col gap-1">
                                    <span
                                        className={variant.judged_runs < variant.total_runs ? 'text-danger' : undefined}
                                    >{`${variant.judged_runs} of ${variant.total_runs}`}</span>
                                    {variant.excluded_runs > 0 && (
                                        <span className="text-xs text-muted">{`${pluralize(variant.excluded_runs, 'run')} not judged`}</span>
                                    )}
                                    {variant.judge_errors > 0 && (
                                        <span className="text-xs text-danger">{`${pluralize(variant.judge_errors, 'run')} could not be judged`}</span>
                                    )}
                                </div>
                            ),
                        },
                        {
                            title: 'Cost',
                            key: 'cost',
                            width: 105,
                            tooltip:
                                'Total scout cost. Unavailable if any run is missing cost. Judging charges are separate.',
                            render: (_, { costUsd }) => (
                                <span className={costUsd === null ? 'text-muted' : undefined}>
                                    {costUsd === null ? 'Unavailable' : formatRunCost(costUsd)}
                                </span>
                            ),
                        },
                        {
                            title: 'Avg time',
                            key: 'duration',
                            width: 100,
                            render: (_, { averageDurationSeconds }) => (
                                <span className={averageDurationSeconds === null ? 'text-muted' : undefined}>
                                    {averageDurationSeconds === null
                                        ? 'Unavailable'
                                        : formatRunDuration(averageDurationSeconds)}
                                </span>
                            ),
                        },
                    ]}
                />
                <p className="m-0 text-xs text-muted">
                    Pass rates average the judged runs. Unknown and not applicable checks are left out of the rate.
                </p>
            </section>

            <section className="flex min-w-0 flex-col gap-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                        <h3 className="m-0 text-sm font-semibold">Check by check</h3>
                        <p className="m-0 text-xs text-muted">How many runs of each version passed each check.</p>
                    </div>
                    <LemonSwitch
                        checked={differencesOnly}
                        onChange={(value) => setFilter({ evaluationId: report.evaluation_id, differencesOnly: value })}
                        label={`Only checks that differ (${differingChecks.length} of ${checks.length})`}
                        data-attr="scout-trial-check-differences"
                    />
                </div>
                <LemonTable<TrialCheckRow>
                    dataSource={differencesOnly ? differingChecks : checks}
                    rowKey={({ criterion }) => criterion.id}
                    size="small"
                    firstColumnSticky
                    emptyState="Every version got the same result on every check."
                    columns={[
                        {
                            title: 'Check',
                            key: 'check',
                            width: 220,
                            render: (_, { criterion }) => (
                                <span className="block min-w-48 font-medium">{criterion.title}</span>
                            ),
                        },
                        ...versions.map(({ variant, letter }, index) => ({
                            title: (
                                <Tooltip title={variant.label}>
                                    <span className="line-clamp-2 min-w-20">{`${letter} · ${variant.label}`}</span>
                                </Tooltip>
                            ),
                            key: variant.variant_id,
                            width: 110,
                            align: 'center' as const,
                            render: (_: unknown, row: TrialCheckRow) => {
                                const cell = row.cells[index]
                                return (
                                    <Tooltip title={cell.description}>
                                        <span
                                            className={`inline-block rounded px-2 py-1 font-semibold ${cell.state === 'fail' ? 'bg-danger-highlight text-danger' : cell.state === 'pass' ? 'text-success' : cell.state === 'unknown' ? 'text-warning' : 'text-muted'}`}
                                        >
                                            {cell.label}
                                        </span>
                                    </Tooltip>
                                )
                            },
                        })),
                    ]}
                />
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
                    <span>
                        <span className="font-semibold text-success">2/2</span> all judged runs passed
                    </span>
                    <span>
                        <span className="font-semibold text-danger">1/2</span> a run failed
                    </span>
                    <span>
                        <span className="font-semibold text-warning">?</span> unknown or missing result
                    </span>
                    <span>– not applicable</span>
                </div>
            </section>

            <section className="flex min-w-0 flex-col gap-3">
                <h3 className="m-0 text-sm font-semibold">Runs</h3>
                <div className="grid grid-cols-1 gap-3 @3xl:grid-cols-2">
                    {versions.map(({ variant, letter, settings, prompt, runs }) => (
                        <LemonCard key={variant.variant_id} hoverEffect={false} className="min-w-0 p-0 overflow-hidden">
                            <div className="flex flex-col gap-1 border-b bg-surface-secondary p-3">
                                <div className="flex flex-wrap items-center gap-2">
                                    <LemonTag type="muted">{letter}</LemonTag>
                                    <strong className="break-words">{variant.label}</strong>
                                </div>
                                <span className="text-xs text-muted break-words">{`${settings.join(', ')} · ${prompt}`}</span>
                            </div>
                            <div className="flex flex-col divide-y">
                                {runs.map((run, index) => {
                                    const counts = trialRunVerdictCounts(run.criteria ?? [])
                                    const executionStatus =
                                        rows.find((row) => row.launchId === run.launch_id)?.result?.status ??
                                        report.evidence.find((evidence) => evidence.launch_id === run.launch_id)
                                            ?.execution_status
                                    return (
                                        <LemonButton
                                            key={run.launch_id}
                                            type="tertiary"
                                            fullWidth
                                            onClick={() => onSelectRun?.(run.launch_id)}
                                            disabledReason={
                                                !onSelectRun ? 'Open this trial to inspect its runs.' : undefined
                                            }
                                            sideIcon={<IconChevronRight />}
                                            data-attr="scout-trial-open-run"
                                        >
                                            <div className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-2 py-1 text-left">
                                                <span>{`Run ${index + 1} of ${variant.total_runs}`}</span>
                                                {run.status === 'judged' ? (
                                                    <span
                                                        className={`text-xs ${counts.failed ? 'text-danger' : counts.unknown ? 'text-warning' : 'text-muted'}`}
                                                    >{`${counts.passed} passed · ${counts.failed} failed${counts.unknown ? ` · ${counts.unknown} unknown` : ''}`}</span>
                                                ) : (
                                                    <LemonTag
                                                        type={
                                                            run.status === 'judge_error' || executionStatus === 'failed'
                                                                ? 'danger'
                                                                : 'muted'
                                                        }
                                                    >
                                                        {run.status === 'judge_error'
                                                            ? 'Could not be judged'
                                                            : executionStatus === 'failed'
                                                              ? 'Failed · not judged'
                                                              : executionStatus === 'cancelled'
                                                                ? 'Stopped · not judged'
                                                                : 'Not judged'}
                                                    </LemonTag>
                                                )}
                                            </div>
                                        </LemonButton>
                                    )
                                })}
                            </div>
                        </LemonCard>
                    ))}
                </div>
            </section>

            <LemonCollapse
                multiple
                size="small"
                panels={[
                    {
                        key: 'ranking',
                        header: 'How ranking works',
                        content: (
                            <ul className="m-0 flex flex-col gap-2 pl-4 text-sm">
                                <li>The most checks passed across all runs ranks first. Equal totals are a tie.</li>
                                <li>
                                    There is no winner if a run failed, was stopped, could not be judged, or has unknown
                                    checks.
                                </li>
                                <li>
                                    Checks that don't apply aren't counted. Versions need the same number of runs and
                                    applicable checks for a fair comparison.
                                </li>
                                <li>{`The rubric stayed fixed at revision ${report.rubric_revision}. These results describe these runs, not future performance.`}</li>
                            </ul>
                        ),
                    },
                    {
                        key: 'rubric',
                        header: `${rubricLabel}: ${pluralize(report.criteria.length, 'check')} · revision ${report.rubric_revision}`,
                        content: (
                            <LemonCollapse
                                multiple
                                embedded
                                size="small"
                                panels={report.criteria.map((criterion) => ({
                                    key: criterion.id,
                                    header: <span className="break-words">{criterion.title}</span>,
                                    content: (
                                        <div className="flex flex-col gap-2 text-sm break-words">
                                            <p className="m-0">{criterion.description}</p>
                                            <div>
                                                <strong>Passes when</strong>
                                                <p className="m-0">{criterion.pass_condition}</p>
                                            </div>
                                            <p className="m-0 text-muted">{`Applies to: ${criterion.applicability}`}</p>
                                        </div>
                                    ),
                                }))}
                            />
                        ),
                    },
                    !!report.rubric_reference_context && {
                        key: 'rubric-reference',
                        header: 'Scout reference saved with this rubric',
                        content: <ScoutRubricReference reference={report.rubric_reference_context!} />,
                    },
                    !!report.limitations.length && {
                        key: 'limitations',
                        header: 'Evidence limits',
                        content: (
                            <ul className="m-0 flex flex-col gap-2 pl-4 text-sm">
                                {report.limitations.map((limitation) => (
                                    <li key={limitation}>{limitation}</li>
                                ))}
                            </ul>
                        ),
                    },
                    {
                        key: 'evaluation-details',
                        header: 'Technical details',
                        content: (
                            <dl className="m-0 grid grid-cols-1 gap-1 text-xs break-all">
                                <dt className="font-semibold">Judge model</dt>
                                <dd className="m-0 mb-2">{report.judge_model}</dd>
                                <dt className="font-semibold">Judge prompt version</dt>
                                <dd className="m-0 mb-2">{report.judge_prompt_version}</dd>
                                <dt className="font-semibold">Judging attempt</dt>
                                <dd className="m-0">{report.evaluation_id}</dd>
                            </dl>
                        ),
                    },
                ]}
            />
        </div>
    )
}

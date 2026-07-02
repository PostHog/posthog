/** Workflow page — the repo skeleton, one level down. Faked data throughout. */

import { LemonCard, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'

import { RangeBar } from '../components/RangeBar'
import { RunActivityChart } from '../components/RunActivityChart'
import {
    DAY_LABELS,
    MOCK_JOB_AGGREGATES,
    MOCK_RECENT_RUNS,
    MockJob,
    MockJobAggregate,
    MockRun,
    daySeries,
    failedShardsLabel,
    groupJobs,
    mockActivityRuns,
    mockJobs,
    mockJobsBackendFull,
    mockWorkflow,
} from './mockData'
import {
    AuthorChip,
    CiTag,
    DeltaBadge,
    GroupDots,
    MockEntityHeader,
    MockHeaderBar,
    MockJobsTable,
    MockLink,
    MockStatTile,
    PercentileBadge,
    Section,
    SectionNav,
    ShareRow,
    StatusDot,
    VerdictPill,
    fmtK,
    fmtMin,
    fmtPct,
    fmtUsd,
} from './shared'

export function MockWorkflowPage({ slug }: { slug: string }): JSX.Element {
    const w = mockWorkflow(slug)
    const failing = w.onMaster === 'failing'
    // Backend CI carries the real 60+-job matrix; other workflows a small flat job set
    const jobsForRun = (runId: number, runFailing: boolean): MockJob[] =>
        w.slug === 'backend-ci'
            ? mockJobsBackendFull(runId, runFailing)
            : mockJobs(runId, runFailing, w.slug === 'e2e-ci' ? 'e2e (chromium)' : 'Django tests')

    return (
        <div>
            <MockHeaderBar crumbs={[{ label: w.name }]} />
            <MockEntityHeader
                icon="⚙️"
                title={w.name}
                slug={
                    <>
                        .github/workflows/{w.slug}.yml ·{' '}
                        <span className="cursor-pointer text-link">View on GitHub ↗</span>
                    </>
                }
                right={
                    failing ? (
                        <VerdictPill kind="danger">Failing on master · 38m</VerdictPill>
                    ) : (
                        <VerdictPill kind="success">Passing on master</VerdictPill>
                    )
                }
            />
            <div className="mt-4 flex flex-wrap gap-2.5">
                <MockStatTile
                    label="Pass rate · 30d"
                    value={fmtPct(w.passRate)}
                    delta={<DeltaBadge value={w.passRateDeltaPp} unit="pp" />}
                    spark={w.passSeries.map((v) => v * 100)}
                    badge={
                        w.passRate < 0.8 ? (
                            <PercentileBadge>lower than 90% of workflows in this repo</PercentileBadge>
                        ) : undefined
                    }
                    sub="workflow-level verdicts"
                />
                <MockStatTile
                    label="Runs · 30d"
                    value={fmtK(w.runs30d)}
                    sub={`≈ ${Math.round(w.runs30d / 30)} per day`}
                />
                <MockStatTile
                    label="Duration p50 → p95"
                    value={`${w.p50Min}m`}
                    valueSuffix={`→ ${w.p95Min}m`}
                    delta={<DeltaBadge value={w.p95DeltaMin} unit="m" goodWhenDown />}
                    sub={`p95 ${w.p95DeltaMin > 0 ? 'slower' : 'faster'} than prior 30d`}
                />
                <MockStatTile
                    label="Queue time p50"
                    value="48"
                    valueSuffix="seconds"
                    delta={<DeltaBadge value={-12} unit="s" goodWhenDown />}
                    sub="created → started, across jobs"
                />
                <MockStatTile
                    label="Cost · 30d"
                    value={fmtUsd(w.cost30d)}
                    delta={<DeltaBadge value={w.costDeltaPct} goodWhenDown />}
                    sub={`${fmtK(w.cost30d * 10)} billable min · ${fmtUsd(w.cost30d / w.runs30d)} per run`}
                />
            </div>
            <SectionNav
                items={[
                    { id: 'health', label: 'Health' },
                    { id: 'jobs', label: 'Jobs' },
                    { id: 'cost', label: 'Cost' },
                    { id: 'runs', label: 'Runs' },
                ]}
            />

            <Section
                id="health"
                title="Health"
                note="every run in the window — duration, verdict, and in-flight load in one plot"
            >
                <RunActivityChart
                    runs={mockActivityRuns(80 + w.runs30d, 140, 1 - w.passRate, w.p50Min)}
                    title={`Run activity · ${w.name}`}
                />
            </Section>

            <Section
                id="jobs"
                title="Jobs"
                note="matrix jobs roll up into one row; jobs always need their run as context, so there's no job page — expand a run below instead"
            >
                <LemonCard hoverEffect={false} className="p-0">
                    <LemonTable<MockJobAggregate>
                        dataSource={MOCK_JOB_AGGREGATES}
                        size="small"
                        embedded
                        columns={[
                            {
                                title: 'Job',
                                render: (_, j) => (
                                    <span className="flex items-center gap-2">
                                        <span className="font-mono text-xs">{j.name}</span>
                                        {j.matrixSize && <LemonTag type="muted">×{j.matrixSize} matrix</LemonTag>}
                                    </span>
                                ),
                            },
                            {
                                title: 'Runs in',
                                align: 'right',
                                tooltip: 'Share of workflow runs this job actually ran in — conditional jobs skip',
                                render: (_, j) => (
                                    <span className={j.runShare < 1 ? 'tabular-nums text-secondary' : 'tabular-nums'}>
                                        {fmtPct(j.runShare)} of runs
                                    </span>
                                ),
                            },
                            {
                                title: 'Queue p50',
                                align: 'right',
                                tooltip: 'created → started — where runner capacity problems hide, per job',
                                render: (_, j) => (
                                    <span className="tabular-nums text-tertiary">{fmtMin(j.queueP50Min)}</span>
                                ),
                            },
                            {
                                title: 'p50 → p95',
                                align: 'right',
                                render: (_, j) => {
                                    const maxJobP95 = Math.max(...MOCK_JOB_AGGREGATES.map((a) => a.p50Min * 1.8))
                                    return (
                                        <span className="inline-block text-right">
                                            <span className="tabular-nums">
                                                {j.p50Min}m{' '}
                                                <span className="text-tertiary">→ {Math.round(j.p50Min * 1.8)}m</span>
                                            </span>
                                            <RangeBar
                                                fraction={j.p50Min / maxJobP95}
                                                tickFraction={(j.p50Min * 1.8) / maxJobP95}
                                                className="mt-0.5 block w-16"
                                                tooltip={`p50 ${j.p50Min}m (fill) → p95 ${Math.round(j.p50Min * 1.8)}m (tick), scaled to the slowest job`}
                                            />
                                        </span>
                                    )
                                },
                            },
                            {
                                title: 'Failure rate',
                                align: 'right',
                                render: (_, j) => (
                                    <span
                                        className={j.failureRate > 0.05 ? 'font-semibold text-danger' : 'font-semibold'}
                                    >
                                        {Math.round(j.failureRate * 100)}%
                                    </span>
                                ),
                            },
                            {
                                title: 'Retries · 30d',
                                align: 'right',
                                render: (_, j) => <span className="tabular-nums">{j.retries30d}</span>,
                            },
                            {
                                title: 'Cost · 30d',
                                width: 210,
                                render: (_, j) => (
                                    <span className="flex items-center gap-2">
                                        <span className="relative h-1.5 w-24 overflow-hidden rounded-full bg-fill-secondary">
                                            <span
                                                className="absolute inset-y-0 left-0 rounded-full"
                                                style={{
                                                    width: `${j.costShare * 100}%`,
                                                    backgroundColor: 'var(--brand-blue)',
                                                }}
                                            />
                                        </span>
                                        <span className="text-xs tabular-nums">
                                            {fmtUsd(j.costShare * w.cost30d)}
                                            <span className="ml-1 text-tertiary">{Math.round(j.costShare * 100)}%</span>
                                        </span>
                                    </span>
                                ),
                            },
                        ]}
                    />
                </LemonCard>
            </Section>

            <Section id="cost" title="Cost">
                <div className="grid gap-2.5 lg:grid-cols-2">
                    <LemonCard hoverEffect={false} className="p-4">
                        <h3 className="mb-2 text-xs font-semibold text-secondary">Cost per day</h3>
                        <Sparkline
                            type="bar"
                            className="h-32 w-full"
                            data={[
                                {
                                    name: 'Cost ($)',
                                    values: DAY_LABELS.map((_, i) =>
                                        Math.round(w.cost30d / 30 + daySeries(320, 0, w.cost30d / 90)[i])
                                    ),
                                    color: 'brand-blue',
                                },
                            ]}
                            labels={DAY_LABELS}
                            maximumIndicator={false}
                        />
                    </LemonCard>
                    <LemonCard hoverEffect={false} className="p-4">
                        <h3 className="mb-1 text-xs font-semibold text-secondary">By runner tier</h3>
                        <ShareRow
                            label={<span className="font-mono text-xs">depot-ubuntu-latest-4</span>}
                            value={fmtUsd(w.cost30d * 0.7)}
                            share={0.7}
                            color="var(--brand-blue)"
                        />
                        <ShareRow
                            label={<span className="font-mono text-xs">depot-ubuntu-latest</span>}
                            value={fmtUsd(w.cost30d * 0.24)}
                            share={0.24}
                            color="var(--brand-blue)"
                        />
                        <ShareRow
                            label={<span className="font-mono text-xs">ubuntu-latest (GitHub-hosted)</span>}
                            value="free"
                            share={0.06}
                            color="var(--muted)"
                        />
                        <div className="mt-2 border-t border-primary pt-2 text-[11px] text-tertiary">
                            Tier parsed from job labels; rate ladder in the cost model.
                        </div>
                    </LemonCard>
                </div>
            </Section>

            <Section
                id="runs"
                title="Runs"
                note={`latest first — expand a run for its jobs; ${w.slug === 'backend-ci' ? 'these runs carry 60+ jobs, grouped by matrix' : 'dots are matrix groups, not raw jobs'}`}
            >
                <LemonCard hoverEffect={false} className="p-0">
                    <LemonTable<MockRun>
                        dataSource={MOCK_RECENT_RUNS}
                        size="small"
                        embedded
                        expandable={{
                            expandedRowRender: (r) => (
                                <div className="p-3">
                                    <MockJobsTable jobs={jobsForRun(r.id, r.conclusion === 'failure')} />
                                    <div className="mt-2 text-xs">
                                        <MockLink to={{ page: 'run', id: r.id }}>Open run #{r.id} →</MockLink>
                                    </div>
                                </div>
                            ),
                        }}
                        columns={[
                            {
                                title: 'Run',
                                render: (_, r) => (
                                    <MockLink to={{ page: 'run', id: r.id }}>
                                        <span className="font-mono text-xs">#{r.id}</span>
                                    </MockLink>
                                ),
                            },
                            { title: 'Conclusion', render: (_, r) => <CiTag ci={r.conclusion} /> },
                            {
                                title: 'Jobs',
                                tooltip:
                                    'One dot per matrix group — a run is a rollup of its jobs, failing groups are named',
                                render: (_, r) => {
                                    const groups = groupJobs(jobsForRun(r.id, r.conclusion === 'failure'))
                                    const failing = groups.filter((g) => g.failed.length > 0)
                                    return (
                                        <span>
                                            <GroupDots groups={groups} />
                                            {failing.length > 0 && (
                                                <span className="mt-0.5 block font-mono text-[10.5px] text-danger">
                                                    {failing
                                                        .map((g) => `${g.base}: ${failedShardsLabel(g)}`)
                                                        .join(' · ')}
                                                </span>
                                            )}
                                        </span>
                                    )
                                },
                            },
                            {
                                title: 'Branch',
                                render: (_, r) => (
                                    <span className="flex items-center gap-1.5 font-mono text-xs">
                                        {r.branch === 'master' && (
                                            <StatusDot kind={r.conclusion === 'failure' ? 'danger' : 'success'} />
                                        )}
                                        {r.branch}
                                    </span>
                                ),
                            },
                            {
                                title: 'Commit',
                                render: (_, r) => <span className="font-mono text-xs text-tertiary">{r.sha}</span>,
                            },
                            {
                                title: 'PR',
                                render: (_, r) =>
                                    r.prNumber ? (
                                        <MockLink to={{ page: 'pr', number: r.prNumber }}>#{r.prNumber}</MockLink>
                                    ) : (
                                        <span className="text-tertiary">—</span>
                                    ),
                            },
                            {
                                title: 'Author',
                                render: (_, r) => <AuthorChip handle={r.author} />,
                            },
                            {
                                title: 'Attempt',
                                align: 'right',
                                render: (_, r) =>
                                    r.attempt > 1 ? (
                                        <LemonTag type="warning">{r.attempt}</LemonTag>
                                    ) : (
                                        <span className="tabular-nums">{r.attempt}</span>
                                    ),
                            },
                            {
                                title: 'Queue',
                                align: 'right',
                                render: (_, r) => (
                                    <span className="tabular-nums text-tertiary">{fmtMin(r.queueMin)}</span>
                                ),
                            },
                            {
                                title: 'Duration',
                                align: 'right',
                                render: (_, r) => <span className="tabular-nums">{r.durationMin}m</span>,
                            },
                            {
                                title: 'Cost',
                                align: 'right',
                                render: (_, r) => <span className="tabular-nums">{fmtUsd(r.costUsd)}</span>,
                            },
                            {
                                title: 'Started',
                                align: 'right',
                                render: (_, r) => <span className="whitespace-nowrap text-tertiary">{r.when}</span>,
                            },
                        ]}
                    />
                    <div className="border-t border-primary px-4 py-2 text-[11px] text-tertiary">
                        Showing 6 of {fmtK(w.runs30d)} runs in the window.
                    </div>
                </LemonCard>
            </Section>
        </div>
    )
}

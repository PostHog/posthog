/** Workflow page — the repo skeleton, one level down. Faked data throughout. */

import { LemonBanner, LemonCard, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { RunActivityChart } from '../components/RunActivityChart'
import {
    DAY_LABELS,
    MOCK_JOB_AGGREGATES,
    MOCK_LOG_E2E,
    MOCK_RECENT_RUNS,
    MockRun,
    daySeries,
    mockActivityRuns,
    mockJobs,
    mockWorkflow,
} from './mockData'
import {
    ChartLegend,
    CiTag,
    DeltaBadge,
    JobsGantt,
    LensPath,
    LineChartSvg,
    LogRows,
    MockEntityHeader,
    MockLink,
    MockScopeBar,
    MockStatTile,
    PercentileBadge,
    Section,
    SectionNav,
    ShareRow,
    StackedColumnsSvg,
    StatusDot,
    VerdictPill,
    fmtK,
    fmtPct,
    fmtUsd,
    useMockNav,
} from './shared'

export function MockWorkflowPage({ slug }: { slug: string }): JSX.Element {
    const { go } = useMockNav()
    const w = mockWorkflow(slug)
    const failing = w.onMaster === 'failing'

    return (
        <div>
            <LensPath
                items={[
                    { level: 'product', label: 'Engineering analytics' },
                    { level: 'repo', label: 'PostHog/posthog', to: { page: 'repo' } },
                    { level: 'workflow', label: w.name, current: true },
                ]}
            />
            <MockScopeBar />
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
                    sub={`${fmtUsd(w.cost30d / w.runs30d)} per run`}
                />
            </div>
            <SectionNav
                items={[
                    { id: 'now', label: 'Now' },
                    { id: 'health', label: 'Health' },
                    { id: 'jobs', label: 'Jobs' },
                    { id: 'cost', label: 'Cost' },
                    { id: 'runs', label: 'Runs' },
                ]}
            />

            <Section id="now" title="What's failing now">
                {failing ? (
                    <>
                        <LemonBanner
                            type="error"
                            action={{ children: 'Open latest red run', onClick: () => go({ page: 'run', id: 41397 }) }}
                        >
                            <strong>Failing on master for 38 minutes</strong> — 3 consecutive red runs, same spec each
                            time. First red run <MockLink to={{ page: 'run', id: 41390 }}>#41390</MockLink> after commit{' '}
                            <span className="font-mono">593064b</span>
                        </LemonBanner>
                        <div className="mt-2.5">
                            <LogRows
                                lines={MOCK_LOG_E2E}
                                header={
                                    <>
                                        Failure excerpt
                                        <span className="font-mono font-normal text-tertiary">
                                            e2e (chromium, shard 3/8) · run #41397
                                        </span>
                                        <span className="ml-auto">
                                            <MockLink to={{ page: 'run', id: 41397 }}>Open run →</MockLink>
                                        </span>
                                    </>
                                }
                            />
                        </div>
                    </>
                ) : (
                    <LemonBanner type="success">
                        <strong>Passing on master</strong> — last failure {w.lastFailure}. Nothing needs attention in
                        this workflow right now.
                    </LemonBanner>
                )}
            </Section>

            <Section id="health" title="Health" note="success rate and duration, trended over the window">
                <div className="grid gap-2.5 lg:grid-cols-2">
                    <LemonCard hoverEffect={false} className="p-4">
                        <h3 className="mb-2 text-xs font-semibold text-secondary">Success rate · 14d</h3>
                        <LineChartSvg
                            series={[
                                {
                                    name: 'Success rate',
                                    pts: w.passSeries.map((v) => v * 100),
                                    color: 'var(--brand-blue)',
                                    fill: true,
                                },
                            ]}
                            yFmt={(v) => `${Math.round(v)}%`}
                            yMin={50}
                            yMax={100}
                        />
                    </LemonCard>
                    <LemonCard hoverEffect={false} className="p-4">
                        <h3 className="mb-2 text-xs font-semibold text-secondary">Duration · 14d</h3>
                        <LineChartSvg
                            series={[
                                {
                                    name: 'p95',
                                    pts: daySeries(300 + w.runs30d, w.p95Min, w.p95Min * 0.12, w.p95DeltaMin / 14),
                                    color: 'var(--border-bold)',
                                },
                                {
                                    name: 'p50',
                                    pts: daySeries(301 + w.runs30d, w.p50Min, w.p50Min * 0.08),
                                    color: 'var(--brand-blue)',
                                },
                            ]}
                            yFmt={(v) => `${Math.round(v)}m`}
                        />
                        <ChartLegend
                            items={[
                                { label: 'p50', color: 'var(--brand-blue)', line: true },
                                { label: 'p95', color: 'var(--border-bold)', line: true },
                            ]}
                        />
                    </LemonCard>
                </div>
                <div className="mt-2.5">
                    <RunActivityChart
                        runs={mockActivityRuns(80 + w.runs30d, 140, 1 - w.passRate, w.p50Min)}
                        title={`Run activity · ${w.name}`}
                    />
                </div>
            </Section>

            <Section
                id="jobs"
                title="Jobs"
                note="aggregated across every run in the window — jobs always need their run as context, so there's no job page; expand a run below instead"
            >
                <LemonCard hoverEffect={false} className="p-0">
                    <LemonTable
                        dataSource={MOCK_JOB_AGGREGATES}
                        embedded
                        columns={[
                            { title: 'Job', render: (_, j) => <span className="font-mono text-xs">{j.name}</span> },
                            {
                                title: 'p50 duration',
                                align: 'right',
                                render: (_, j) => <span className="tabular-nums">{j.p50Min}m</span>,
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
                                title: 'Cost share',
                                width: 200,
                                render: (_, j) => (
                                    <span className="flex items-center gap-2">
                                        <span className="relative h-1.5 w-28 overflow-hidden rounded-full bg-fill-secondary">
                                            <span
                                                className="absolute inset-y-0 left-0 rounded-full"
                                                style={{
                                                    width: `${j.costShare * 100}%`,
                                                    backgroundColor: 'var(--brand-blue)',
                                                }}
                                            />
                                        </span>
                                        <span className="text-xs tabular-nums text-secondary">
                                            {Math.round(j.costShare * 100)}%
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
                        <StackedColumnsSvg
                            data={DAY_LABELS.map((_, i) => ({
                                usd: w.cost30d / 30 + daySeries(320, 0, w.cost30d / 90)[i],
                            }))}
                            keys={['usd']}
                            colors={['var(--brand-blue)']}
                            yFmt={(v) => `$${Math.round(v)}`}
                            height={150}
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

            <Section id="runs" title="Runs" note="latest first — expand a run for its jobs without leaving the page">
                <LemonCard hoverEffect={false} className="p-0">
                    <LemonTable<MockRun>
                        dataSource={MOCK_RECENT_RUNS}
                        embedded
                        expandable={{
                            expandedRowRender: (r) => (
                                <div className="p-3">
                                    <JobsGantt jobs={mockJobs(r.id, r.conclusion === 'failure')} />
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
                                title: 'PR',
                                render: (_, r) =>
                                    r.prNumber ? (
                                        <MockLink to={{ page: 'pr', number: r.prNumber }}>#{r.prNumber}</MockLink>
                                    ) : (
                                        <span className="text-tertiary">—</span>
                                    ),
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
                                title: 'Duration',
                                align: 'right',
                                render: (_, r) => <span className="tabular-nums">{r.durationMin}m</span>,
                            },
                            {
                                title: 'Started',
                                align: 'right',
                                render: (_, r) => <span className="text-tertiary">{r.when}</span>,
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

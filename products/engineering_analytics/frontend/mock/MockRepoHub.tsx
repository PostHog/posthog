/** Repo hub — the new entry point of the lens stack. Faked data throughout. */

import { LemonCard, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'

import { FailureSparkline } from '../components/FailureSparkline'
import { RunActivityChart } from '../components/RunActivityChart'
import {
    DAY_LABELS,
    MOCK_AUTHORS,
    MOCK_FAILURES,
    MOCK_PRS,
    MOCK_RUNNER_TIERS,
    MOCK_WORKFLOWS,
    MockFailure,
    MockWorkflow,
    daySeries,
    mockActivityRuns,
} from './mockData'
import {
    CiTag,
    DeltaBadge,
    LogRows,
    MockEntityHeader,
    MockHeaderBar,
    MockLink,
    MockPrTable,
    MockStatTile,
    Section,
    SectionNav,
    ShareRow,
    StatusDot,
    VerdictPill,
    fmtK,
    fmtPct,
    fmtUsd,
    useMockNav,
} from './shared'

const REPO_RUNS_30D = 18190
const REPO_COST_30D = 11400

const WORKFLOW_SHARE_COLORS = [
    'var(--brand-blue)',
    'var(--success)',
    'var(--warning)',
    'var(--purple)',
    'var(--danger)',
]

export function MockRepoHub(): JSX.Element {
    const { go } = useMockNav()
    const masterPass = daySeries(210, 0.93, 0.03, -0.004).map((v, i) => (i > 10 ? v - 0.07 : v)) // dips in the last days
    const topByCost = [...MOCK_WORKFLOWS].sort((a, b) => b.cost30d - a.cost30d)
    const totalCost = MOCK_WORKFLOWS.reduce((a, w) => a + w.cost30d, 0)
    const top5 = topByCost.slice(0, 5)
    const otherCost = totalCost - top5.reduce((a, w) => a + w.cost30d, 0)
    const openPrs = MOCK_PRS.filter((p) => p.state === 'open')

    return (
        <div>
            <MockHeaderBar />
            <MockEntityHeader
                icon="📦"
                title="posthog"
                slug={
                    <>
                        PostHog/posthog · <span className="cursor-pointer text-link">View on GitHub ↗</span>
                    </>
                }
                right={<VerdictPill kind="danger">1 workflow failing on master</VerdictPill>}
            />
            <div className="mt-4 flex flex-wrap gap-2.5">
                <MockStatTile
                    label="Pass rate · all workflows"
                    value="89%"
                    delta={<DeltaBadge value={-2} unit="pp" />}
                    spark={daySeries(220, 89, 2, -0.1)}
                    sub="workflow-level, all branches"
                />
                <MockStatTile
                    label="Runs · 30d"
                    value={fmtK(REPO_RUNS_30D)}
                    delta={<DeltaBadge value={6} />}
                    spark={daySeries(221, 600, 80, 4)}
                    sub="≈ 610 per day"
                />
                <MockStatTile
                    label="CI cost · 30d"
                    value={fmtUsd(REPO_COST_30D)}
                    delta={<DeltaBadge value={9} goodWhenDown />}
                    spark={daySeries(222, 380, 40, 3)}
                    sub="billable minutes × tier rate"
                />
                <MockStatTile
                    label="Median PR open→merge"
                    value="21"
                    valueSuffix="hours"
                    delta={<DeltaBadge value={-3} unit="h" goodWhenDown />}
                    sub="bots and drafts excluded"
                />
                <MockStatTile
                    label="Re-run cycles · 30d"
                    value="312"
                    delta={<DeltaBadge value={18} goodWhenDown />}
                    sub="runs with attempt > 1"
                />
            </div>
            <SectionNav
                items={[
                    { id: 'now', label: 'Now' },
                    { id: 'master', label: 'Master health' },
                    { id: 'prs', label: 'Pull requests' },
                    { id: 'workflows', label: 'Workflows' },
                    { id: 'cost', label: 'Cost' },
                    { id: 'activity', label: 'Activity' },
                    { id: 'authors', label: 'Authors' },
                ]}
            />

            <Section id="now" title="Latest failures" note="the triage layer — everything below is trends">
                <LemonCard hoverEffect={false} className="p-0">
                    <LemonTable<MockFailure>
                        dataSource={MOCK_FAILURES}
                        embedded
                        expandable={{
                            expandedRowRender: (f) => (
                                <div className="p-2">
                                    <LogRows
                                        lines={f.log}
                                        header={
                                            <>
                                                Failure excerpt
                                                <span className="font-mono font-normal text-tertiary">
                                                    run #{f.runId}
                                                </span>
                                                <span className="ml-auto">
                                                    <MockLink to={{ page: 'run', id: f.runId }}>Open run →</MockLink>
                                                </span>
                                            </>
                                        }
                                    />
                                </div>
                            ),
                        }}
                        columns={[
                            {
                                title: 'Workflow',
                                render: (_, f) => (
                                    <span className="flex items-center gap-2 font-medium">
                                        <StatusDot kind="danger" />
                                        <MockLink to={{ page: 'workflow', slug: f.workflowSlug }}>
                                            {f.workflow}
                                        </MockLink>
                                    </span>
                                ),
                            },
                            {
                                title: 'Run',
                                render: (_, f) => (
                                    <MockLink to={{ page: 'run', id: f.runId }}>
                                        <span className="font-mono text-xs">#{f.runId}</span>
                                    </MockLink>
                                ),
                            },
                            {
                                title: 'Branch',
                                render: (_, f) => <span className="font-mono text-xs">{f.branch}</span>,
                            },
                            {
                                title: 'What failed',
                                render: (_, f) => <span className="text-secondary">{f.summary}</span>,
                            },
                            {
                                title: 'When',
                                align: 'right',
                                render: (_, f) => <span className="text-tertiary">{f.when}</span>,
                            },
                        ]}
                    />
                    <div className="border-t border-primary px-4 py-2 text-[11px] text-tertiary">
                        Failure summaries come from ingested CI failure logs — expand a row to read them without leaving
                        for GitHub.
                    </div>
                </LemonCard>
            </Section>

            <Section
                id="master"
                title="Master health"
                note="the default branch gets its own trend — not buried in a filter"
            >
                <div className="grid gap-2.5 lg:grid-cols-2">
                    <LemonCard hoverEffect={false} className="p-4">
                        <h3 className="mb-2 text-xs font-semibold text-secondary">Success rate on master · 14d</h3>
                        <Sparkline
                            type="line"
                            className="h-32 w-full"
                            data={[
                                {
                                    name: 'Success rate (%)',
                                    values: masterPass.map((v) => Math.round(v * 100)),
                                    color: 'brand-blue',
                                },
                            ]}
                            labels={DAY_LABELS}
                            maximumIndicator={false}
                        />
                    </LemonCard>
                    <LemonCard hoverEffect={false} className="p-4">
                        <h3 className="mb-2 text-xs font-semibold text-secondary">Time master spent red · per day</h3>
                        <Sparkline
                            type="bar"
                            className="h-32 w-full"
                            data={[
                                {
                                    name: 'Minutes red',
                                    values: DAY_LABELS.map((_, i) =>
                                        Math.round(Math.max(0, daySeries(230, 30, 28)[i] - (i < 11 ? 18 : -8)))
                                    ),
                                    color: 'danger',
                                },
                            ]}
                            labels={DAY_LABELS}
                            maximumIndicator={false}
                        />
                        <div className="mt-2 border-t border-primary pt-2 text-[11px] text-tertiary">
                            A day counts as red while any required workflow's latest master run is failing.
                        </div>
                    </LemonCard>
                </div>
            </Section>

            <Section
                id="prs"
                title="Open pull requests"
                note="same table as the author page — one component, one column set"
            >
                <LemonCard hoverEffect={false} className="p-0">
                    <MockPrTable prs={openPrs} />
                </LemonCard>
            </Section>

            <Section
                id="workflows"
                title="Workflows"
                note="every row opens the workflow page — same skeleton, one level down"
            >
                <LemonCard hoverEffect={false} className="p-0">
                    <LemonTable<MockWorkflow>
                        dataSource={topByCost}
                        embedded
                        onRow={(w) => ({ onClick: () => go({ page: 'workflow', slug: w.slug }) })}
                        columns={[
                            {
                                title: 'Workflow',
                                render: (_, w) => (
                                    <span className="flex items-center gap-2 font-medium">
                                        <StatusDot kind={w.onMaster === 'failing' ? 'danger' : 'success'} />
                                        <MockLink to={{ page: 'workflow', slug: w.slug }}>{w.name}</MockLink>
                                    </span>
                                ),
                            },
                            { title: 'On master', render: (_, w) => <CiTag ci={w.onMaster} /> },
                            {
                                title: 'Runs',
                                align: 'right',
                                render: (_, w) => <span className="tabular-nums">{fmtK(w.runs30d)}</span>,
                            },
                            {
                                title: 'Pass rate',
                                align: 'right',
                                render: (_, w) => (
                                    <span
                                        className={
                                            w.passRate < 0.8
                                                ? 'font-semibold text-danger'
                                                : w.passRate < 0.92
                                                  ? 'font-semibold text-warning-dark'
                                                  : 'font-semibold'
                                        }
                                    >
                                        {fmtPct(w.passRate)}
                                    </span>
                                ),
                            },
                            {
                                title: 'Δ 30d',
                                align: 'right',
                                render: (_, w) => <DeltaBadge value={w.passRateDeltaPp} unit="pp" />,
                            },
                            {
                                title: 'p50',
                                align: 'right',
                                render: (_, w) => <span className="tabular-nums">{w.p50Min}m</span>,
                            },
                            {
                                title: 'p95',
                                align: 'right',
                                render: (_, w) => <span className="tabular-nums">{w.p95Min}m</span>,
                            },
                            {
                                title: 'Cost · 30d',
                                align: 'right',
                                render: (_, w) => <span className="tabular-nums">{fmtUsd(w.cost30d)}</span>,
                            },
                            {
                                title: 'Failures · 14d',
                                width: 110,
                                render: (_, w) => (
                                    <FailureSparkline
                                        completed={w.completed}
                                        failures={w.failures}
                                        labels={DAY_LABELS}
                                        ariaLabel={`${w.name} failures`}
                                        className="h-6 w-24"
                                    />
                                ),
                            },
                            {
                                title: 'Last failure',
                                align: 'right',
                                render: (_, w) => <span className="text-tertiary">{w.lastFailure}</span>,
                            },
                        ]}
                    />
                </LemonCard>
            </Section>

            <Section id="cost" title="Cost" note="where the 30-day spend goes">
                <div className="grid gap-2.5 lg:grid-cols-2">
                    <LemonCard hoverEffect={false} className="p-4">
                        <h3 className="mb-1 text-xs font-semibold text-secondary">By workflow</h3>
                        {top5.map((w, i) => (
                            <ShareRow
                                key={w.slug}
                                label={w.name}
                                value={fmtUsd(w.cost30d)}
                                valueSub={`${Math.round((w.cost30d / totalCost) * 100)}% of total`}
                                share={w.cost30d / totalCost}
                                color={WORKFLOW_SHARE_COLORS[i]}
                                to={{ page: 'workflow', slug: w.slug }}
                            />
                        ))}
                        <ShareRow
                            label="Other (5 workflows)"
                            value={fmtUsd(otherCost)}
                            valueSub={`${Math.round((otherCost / totalCost) * 100)}% of total`}
                            share={otherCost / totalCost}
                            color="var(--muted)"
                        />
                        <div className="mt-2 border-t border-primary pt-2 text-[11px] text-tertiary">
                            Estimated from billable job minutes × runner-tier rate. GitHub-hosted runners are free tier.
                        </div>
                    </LemonCard>
                    <LemonCard hoverEffect={false} className="p-4">
                        <h3 className="mb-1 text-xs font-semibold text-secondary">By runner tier</h3>
                        {MOCK_RUNNER_TIERS.map((r, i) => (
                            <ShareRow
                                key={r.tier}
                                label={<span className="font-mono text-xs">{r.tier}</span>}
                                sub={`${fmtK(r.jobs)} jobs`}
                                value={r.costUsd ? fmtUsd(r.costUsd) : 'free'}
                                share={r.share}
                                color={
                                    ['var(--brand-blue)', 'var(--brand-blue)', 'var(--muted)', 'var(--brand-blue)'][i]
                                }
                            />
                        ))}
                        <h3 className="mb-1 mt-4 text-xs font-semibold text-secondary">Cost per day</h3>
                        <Sparkline
                            type="bar"
                            className="h-24 w-full"
                            data={[
                                {
                                    name: 'Cost ($)',
                                    values: DAY_LABELS.map((_, i) => Math.round(340 + daySeries(240, 0, 60, 4)[i])),
                                    color: 'brand-blue',
                                },
                            ]}
                            labels={DAY_LABELS}
                            maximumIndicator={false}
                        />
                    </LemonCard>
                </div>
            </Section>

            <Section
                id="activity"
                title="Activity"
                note="the run scatter from the workflow page, one level up — every run in the last 3 days"
            >
                <RunActivityChart runs={mockActivityRuns(77, 260, 0.12, 18)} title="Run activity · all workflows" />
                <LemonCard hoverEffect={false} className="mt-2.5 p-4">
                    <h3 className="mb-2 text-xs font-semibold text-secondary">Failed runs per day</h3>
                    <Sparkline
                        type="bar"
                        className="h-24 w-full"
                        data={[
                            {
                                name: 'Failed runs',
                                values: DAY_LABELS.map((_, i) =>
                                    Math.round(MOCK_WORKFLOWS.reduce((a, w) => a + w.failures[i] / 2.4, 0))
                                ),
                                color: 'danger',
                            },
                        ]}
                        labels={DAY_LABELS}
                        maximumIndicator={false}
                    />
                </LemonCard>
            </Section>

            <Section
                id="authors"
                title="Authors"
                note="who's shipping in the window — click through to their PRs and CI cost"
            >
                <div className="grid gap-2.5 lg:grid-cols-2">
                    <LemonCard hoverEffect={false} className="p-4">
                        <h3 className="mb-1 text-xs font-semibold text-secondary">Most active · by PRs opened</h3>
                        {MOCK_AUTHORS.map((a, i) => (
                            <ShareRow
                                key={a.handle}
                                rank={i + 1}
                                avatar={a.handle}
                                label={a.handle}
                                sub={`median open→merge ${a.medianMergeHours}h`}
                                value={`${a.prs30d} PRs`}
                                valueSub={<DeltaBadge value={a.prsDelta} unit="" />}
                                to={{ page: 'author', handle: a.handle }}
                            />
                        ))}
                    </LemonCard>
                    <LemonCard hoverEffect={false} className="p-4">
                        <h3 className="mb-1 text-xs font-semibold text-secondary">CI cost attributed to their PRs</h3>
                        {[...MOCK_AUTHORS]
                            .sort((a, b) => b.ciCost30d - a.ciCost30d)
                            .map((a, i) => (
                                <ShareRow
                                    key={a.handle}
                                    rank={i + 1}
                                    avatar={a.handle}
                                    label={a.handle}
                                    sub={`${a.rerunCycles} re-run cycles`}
                                    value={fmtUsd(a.ciCost30d)}
                                    valueSub="30d"
                                    to={{ page: 'author', handle: a.handle }}
                                />
                            ))}
                        <div className="mt-2 border-t border-primary pt-2 text-[11px] text-tertiary">
                            Cohort-level by default — author pages exist for finding your own work, not ranking people.
                        </div>
                    </LemonCard>
                </div>
                <div className="mt-2">
                    <LemonTag type="muted">
                        Also on this page later: bot authors (Mendral, Renovate) as a separate cohort
                    </LemonTag>
                </div>
            </Section>
        </div>
    )
}

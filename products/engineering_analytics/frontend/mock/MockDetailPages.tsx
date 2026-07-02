/** Run, PR, and author pages — the same skeleton at the leaf levels. Faked data throughout. */

import { Fragment } from 'react'

import { LemonCard, LemonTable } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { cn } from 'lib/utils/css-classes'

import {
    DAY_LABELS,
    MOCK_LOG_DJANGO,
    MOCK_LOG_E2E,
    MOCK_PRS,
    daySeries,
    mockAuthor,
    mockJobs,
    mockPr,
    mockWorkflow,
} from './mockData'
import {
    AuthorChip,
    CiTag,
    DeltaBadge,
    LogRows,
    MockEntityHeader,
    MockHeaderBar,
    MockJobsTable,
    MockLink,
    MockPrTable,
    MockStatTile,
    PercentileBadge,
    Section,
    SectionNav,
    ShareRow,
    StatusDot,
    VerdictPill,
    fmtHours,
    fmtMin,
    fmtUsd,
    useMockNav,
} from './shared'

/* ============================================================ run ============================================================ */

export function MockRunPage({ id }: { id: number }): JSX.Element {
    const isMasterRun = [41397, 41390].includes(id)
    const failing = [41397, 41393, 41390, 41371].includes(id)
    const w = isMasterRun ? mockWorkflow('e2e-ci') : mockWorkflow('backend-ci')
    const jobs = mockJobs(id, failing, isMasterRun ? 'e2e (chromium)' : 'Django tests')
    const failedJobs = jobs.filter((j) => j.conclusion === 'failure')

    return (
        <div>
            <MockHeaderBar
                crumbs={[{ label: w.name, to: { page: 'workflow', slug: w.slug } }, { label: `#${id}` }]}
                branch={isMasterRun ? 'master' : 'feat/retention-export'}
            />
            <MockEntityHeader
                icon={failing ? '❌' : '✅'}
                title={w.name}
                titleSuffix={`#${id}`}
                slug={
                    <>
                        {isMasterRun ? 'master' : 'feat/retention-export'} · commit{' '}
                        <span className="cursor-pointer text-link">{isMasterRun ? '593064b' : '8e8d604'} ↗</span>
                        {!isMasterRun && (
                            <>
                                {' '}
                                · pull request <MockLink to={{ page: 'pr', number: 67891 }}>#67891</MockLink>
                            </>
                        )}{' '}
                        · attempt 2 · <span className="cursor-pointer text-link">View on GitHub ↗</span>
                    </>
                }
                right={
                    failing ? (
                        <VerdictPill kind="danger">Failure</VerdictPill>
                    ) : (
                        <VerdictPill kind="success">Success</VerdictPill>
                    )
                }
            />
            <div className="mt-4 flex flex-wrap gap-2.5">
                <MockStatTile
                    label="Duration"
                    value="27"
                    valueSuffix="minutes"
                    sub={`critical path of ${jobs.length} jobs · workflow p50 is ${w.p50Min}m`}
                />
                <MockStatTile label="Queue time" value="41" valueSuffix="seconds" sub="created → first job started" />
                <MockStatTile
                    label="Jobs"
                    value={`${jobs.length}`}
                    sub={failing ? '2 failed · 1 skipped' : 'all succeeded'}
                />
                <MockStatTile label="Estimated cost" value="$1.85" sub="sum of billable job minutes × tier rate" />
            </div>

            <Section
                id="run-jobs"
                title="Jobs"
                note="queue then execution, per job — this is where a run becomes explainable"
            >
                <LemonCard hoverEffect={false} className="p-0">
                    <MockJobsTable jobs={jobs} />
                </LemonCard>
            </Section>

            {failing && (
                <Section
                    id="run-failures"
                    title="Failure logs"
                    note="thinned to the lines that matter — full logs on GitHub"
                >
                    <div className="flex flex-col gap-2.5">
                        {failedJobs.map((j) => (
                            <LogRows
                                key={j.name}
                                lines={isMasterRun ? MOCK_LOG_E2E : MOCK_LOG_DJANGO}
                                header={
                                    <>
                                        <StatusDot kind="danger" />
                                        <span className="font-mono">{j.name}</span>
                                        <span className="font-mono font-normal text-tertiary">
                                            failed after {fmtMin(j.durMin)}
                                        </span>
                                    </>
                                }
                            />
                        ))}
                    </div>
                </Section>
            )}
        </div>
    )
}

/* ============================================================ pull request ============================================================ */

const PUSHES = [
    { sha: 'a41f20c', when: 'Jun 30 14:12', ok: true, gap: '26m' },
    { sha: 'b7e91d4', when: 'Jun 30 18:40', ok: true, gap: '4h 28m' },
    { sha: '5c20aa1', when: 'Jul 1 10:05', ok: false, gap: '15h' },
    { sha: '8e8d604', when: 'Jul 2 09:31', ok: false, gap: '23h' },
]

export function MockPrPage({ number }: { number: number }): JSX.Element {
    const { go } = useMockNav()
    const p = mockPr(number)
    const pushes = PUSHES.slice(0, Math.min(p.pushes, 4))
    const prWorkflows = [
        {
            w: mockWorkflow('backend-ci'),
            c: p.ci === 'failing' ? ('failure' as const) : ('success' as const),
            failedJob: 'Django tests (shard 3/6)',
            dur: '24m',
            runs: p.pushes + p.reruns,
        },
        {
            w: mockWorkflow('e2e-ci'),
            c:
                p.ci === 'failing'
                    ? ('failure' as const)
                    : p.ci === 'running'
                      ? ('running' as const)
                      : ('success' as const),
            failedJob: 'e2e (chromium, shard 3/8)',
            dur: '33m',
            runs: p.pushes + p.reruns + 1,
        },
        { w: mockWorkflow('frontend-ci'), c: 'success' as const, failedJob: '', dur: '13m', runs: p.pushes },
        { w: mockWorkflow('lint'), c: 'success' as const, failedJob: '', dur: '4m', runs: p.pushes },
    ]

    return (
        <div>
            <MockHeaderBar crumbs={[{ label: `#${p.number}` }]} branch="feat/retention-export" />
            <MockEntityHeader
                icon={p.state === 'merged' ? '🟣' : '🟢'}
                title={p.title}
                slug={
                    <>
                        PostHog/posthog #{p.number} · <AuthorChip handle={p.author} /> · opened {fmtHours(p.openHours)}{' '}
                        ago · <span className="cursor-pointer text-link">View on GitHub ↗</span>
                    </>
                }
                right={
                    p.state === 'merged' ? (
                        <VerdictPill kind="muted">Merged</VerdictPill>
                    ) : p.ci === 'failing' ? (
                        <VerdictPill kind="danger">CI failing</VerdictPill>
                    ) : p.ci === 'running' ? (
                        <VerdictPill kind="warning">CI running</VerdictPill>
                    ) : (
                        <VerdictPill kind="success">CI passing</VerdictPill>
                    )
                }
            />
            <div className="mt-4 flex flex-wrap gap-2.5">
                <MockStatTile
                    label="CI verdict · latest push"
                    value={p.ci === 'failing' ? '2 / 14' : '14 / 14'}
                    valueSuffix="checks green"
                    sub={p.ci === 'failing' ? 'E2E CI + Backend CI failing' : 'all workflows settled'}
                />
                <MockStatTile
                    label="Pushes → CI triggers"
                    value={`${p.pushes}`}
                    delta={
                        p.reruns ? (
                            <span className="text-xs font-semibold text-warning-dark">+{p.reruns} re-runs</span>
                        ) : undefined
                    }
                    sub={p.reruns ? `${p.reruns} manual re-run cycles on top` : 'no manual re-runs'}
                />
                <MockStatTile
                    label="CI cost so far"
                    value={fmtUsd(p.costUsd)}
                    badge={
                        p.costUsd > 15 ? <PercentileBadge>top 10% of open PRs by CI cost</PercentileBadge> : undefined
                    }
                    sub={`${fmtUsd(p.costUsd / Math.max(1, p.pushes))} per push`}
                />
                <MockStatTile
                    label={p.state === 'merged' ? 'Open → merge' : 'Open so far'}
                    value={fmtHours(p.openHours)}
                    sub="repo median is 21h"
                />
            </div>
            <SectionNav
                items={[
                    { id: 'pr-timeline', label: 'Timeline' },
                    { id: 'pr-failures', label: 'Failures' },
                    { id: 'pr-runs', label: 'CI runs' },
                ]}
            />

            <Section
                id="pr-timeline"
                title="Lifecycle"
                note="every push triggers CI — red nodes had at least one failing workflow"
            >
                <LemonCard hoverEffect={false} className="overflow-x-auto p-4">
                    <div className="flex min-w-[560px] items-start pt-2">
                        <LifecycleNode label="Opened" time="Jun 30 13:58" kind="start" />
                        {pushes.map((push) => (
                            <Fragment key={push.sha}>
                                <LifecycleGap label={push.gap} />
                                <LifecycleNode
                                    label={`push ${push.sha}`}
                                    time={push.when}
                                    kind={push.ok ? 'ok' : 'red'}
                                />
                            </Fragment>
                        ))}
                        <LifecycleGap label="now" />
                        <LifecycleNode
                            label={p.state === 'merged' ? 'Merged' : 'Open'}
                            time={p.state === 'merged' ? 'Jul 1 12:04' : `${fmtHours(p.openHours)} and counting`}
                            kind={p.state === 'merged' ? 'end' : 'open'}
                        />
                    </div>
                </LemonCard>
            </Section>

            <Section
                id="pr-failures"
                title="What's failing on the latest push"
                note="straight from CI failure logs — no tab-switch to GitHub to find out why"
            >
                {p.ci === 'failing' ? (
                    <div className="flex flex-col gap-2.5">
                        <LogRows
                            lines={MOCK_LOG_E2E}
                            header={
                                <>
                                    <StatusDot kind="danger" />
                                    E2E CI · e2e (chromium, shard 3/8)
                                    <span className="ml-auto">
                                        <MockLink to={{ page: 'run', id: 41393 }}>Open run #41393 →</MockLink>
                                    </span>
                                </>
                            }
                        />
                        <LogRows
                            lines={MOCK_LOG_DJANGO}
                            header={
                                <>
                                    <StatusDot kind="danger" />
                                    Backend CI · Django tests (shard 3/6)
                                    <span className="ml-auto">
                                        <MockLink to={{ page: 'run', id: 41371 }}>Open run #41371 →</MockLink>
                                    </span>
                                </>
                            }
                        />
                        <LemonCard hoverEffect={false} className="border-danger bg-fill-error-tertiary p-4">
                            <div className="text-xs font-semibold">Reading of the two failures</div>
                            <div className="mt-1 text-xs text-secondary">
                                Both point at the export route: the API test gets a 404 from{' '}
                                <span className="font-mono">/insights/{'{id}'}/export</span> and the e2e spec never sees
                                the export menu item. Likely the serializer rename moved the action route.
                            </div>
                        </LemonCard>
                    </div>
                ) : (
                    <div className="text-xs text-tertiary">No failing checks on the latest push.</div>
                )}
            </Section>

            <Section
                id="pr-runs"
                title="CI runs · grouped by workflow"
                note="attribution is by PR number, so every push is captured — re-runs fold under their push"
            >
                <LemonCard hoverEffect={false} className="p-0">
                    <LemonTable
                        dataSource={prWorkflows}
                        embedded
                        onRow={(x) => ({ onClick: () => go({ page: 'workflow', slug: x.w.slug }) })}
                        columns={[
                            {
                                title: 'Workflow',
                                render: (_, x) => (
                                    <span className="flex items-center gap-2 font-medium">
                                        <StatusDot
                                            kind={
                                                x.c === 'failure' ? 'danger' : x.c === 'running' ? 'primary' : 'success'
                                            }
                                        />
                                        <MockLink to={{ page: 'workflow', slug: x.w.slug }}>{x.w.name}</MockLink>
                                    </span>
                                ),
                            },
                            { title: 'Latest conclusion', render: (_, x) => <CiTag ci={x.c} /> },
                            {
                                title: 'What failed',
                                render: (_, x) =>
                                    x.c === 'failure' ? (
                                        <span className="font-mono text-[10.5px] text-secondary">{x.failedJob}</span>
                                    ) : (
                                        <span className="text-tertiary">—</span>
                                    ),
                            },
                            {
                                title: 'Runs on this PR',
                                align: 'right',
                                render: (_, x) => <span className="tabular-nums">{x.runs}</span>,
                            },
                            {
                                title: 'Latest duration',
                                align: 'right',
                                render: (_, x) => <span className="tabular-nums">{x.dur}</span>,
                            },
                            {
                                title: '',
                                align: 'right',
                                render: () => <MockLink to={{ page: 'run', id: 41393 }}>latest run →</MockLink>,
                            },
                        ]}
                    />
                </LemonCard>
            </Section>
        </div>
    )
}

function LifecycleNode({
    label,
    time,
    kind,
}: {
    label: string
    time: string
    kind: 'start' | 'ok' | 'red' | 'end' | 'open'
}): JSX.Element {
    return (
        <div className="flex min-w-14 shrink-0 flex-col items-center gap-1">
            <span
                className={cn(
                    'z-10 size-3.5 rounded-full border-2',
                    kind === 'red' ? 'bg-fill-error-tertiary' : kind === 'end' ? 'bg-success' : '',
                    kind === 'start' && 'bg-brand-blue',
                    (kind === 'ok' || kind === 'open') && 'bg-surface-primary'
                )}
                style={{
                    borderColor:
                        kind === 'red' ? 'var(--danger)' : kind === 'end' ? 'var(--success)' : 'var(--brand-blue)',
                }}
            />
            <span className="whitespace-nowrap text-[10.5px] font-medium text-secondary">{label}</span>
            <span className="whitespace-nowrap font-mono text-[9.5px] text-tertiary">{time}</span>
        </div>
    )
}

function LifecycleGap({ label }: { label: string }): JSX.Element {
    return (
        <div className="relative top-[6px] h-0.5 min-w-9 flex-1 bg-fill-secondary">
            <span className="absolute -top-2.5 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full bg-fill-secondary px-2 text-[9.5px] text-secondary">
                {label}
            </span>
        </div>
    )
}

/* ============================================================ author ============================================================ */

export function MockAuthorPage({ handle }: { handle: string }): JSX.Element {
    const a = mockAuthor(handle)
    const prs = MOCK_PRS.filter((p) => p.author === a.handle)
    const rows = prs.length ? prs : MOCK_PRS.slice(0, 3)
    const openCount = rows.filter((p) => p.state === 'open').length

    return (
        <div>
            <MockHeaderBar crumbs={[{ label: a.handle }]} branch="all branches" />
            <MockEntityHeader
                title={a.handle}
                slug={<span className="cursor-pointer text-link">github.com/{a.handle} ↗</span>}
                right={
                    <VerdictPill kind="muted">{openCount === 1 ? '1 open PR' : `${openCount} open PRs`}</VerdictPill>
                }
            />
            <div className="mt-4 flex flex-wrap gap-2.5">
                <MockStatTile
                    label="PRs opened · 30d"
                    value={`${a.prs30d}`}
                    delta={<DeltaBadge value={a.prsDelta} unit="" />}
                    spark={daySeries(400 + a.prs30d, a.prs30d / 4, 1.4)}
                />
                <MockStatTile
                    label="Median open → merge"
                    value={`${a.medianMergeHours}`}
                    valueSuffix="hours"
                    delta={<DeltaBadge value={a.mergeDeltaHours} unit="h" goodWhenDown />}
                    sub="repo median is 21h"
                />
                <MockStatTile
                    label="CI cost · 30d"
                    value={fmtUsd(a.ciCost30d)}
                    delta={<DeltaBadge value={12} goodWhenDown />}
                    sub={`${fmtUsd(a.ciCost30d / a.prs30d)} per PR`}
                />
                <MockStatTile
                    label="Re-run cycles"
                    value={`${a.rerunCycles}`}
                    sub={a.rerunCycles > 8 ? 'high — often a flaky-test signal' : 'in the normal band'}
                />
            </div>
            <SectionNav
                items={[
                    { id: 'author-prs', label: 'Pull requests' },
                    { id: 'author-cost', label: 'Cost' },
                ]}
            />

            <Section
                id="author-prs"
                title="Pull requests"
                note="same table as the repo overview — one component, scoped to one author"
            >
                <LemonCard hoverEffect={false} className="p-0">
                    <MockPrTable prs={rows} showAuthor={false} />
                </LemonCard>
            </Section>

            <Section id="author-cost" title="Where their CI minutes go">
                <div className="grid gap-2.5 lg:grid-cols-2">
                    <LemonCard hoverEffect={false} className="p-4">
                        <h3 className="mb-1 text-xs font-semibold text-secondary">By workflow</h3>
                        <ShareRow
                            label="Backend CI"
                            value={fmtUsd(a.ciCost30d * 0.44)}
                            share={0.44}
                            color="var(--brand-blue)"
                            to={{ page: 'workflow', slug: 'backend-ci' }}
                        />
                        <ShareRow
                            label="E2E CI"
                            value={fmtUsd(a.ciCost30d * 0.31)}
                            share={0.31}
                            color="var(--success)"
                            to={{ page: 'workflow', slug: 'e2e-ci' }}
                        />
                        <ShareRow
                            label="Frontend CI"
                            value={fmtUsd(a.ciCost30d * 0.14)}
                            share={0.14}
                            color="var(--warning)"
                            to={{ page: 'workflow', slug: 'frontend-ci' }}
                        />
                        <ShareRow label="Other" value={fmtUsd(a.ciCost30d * 0.11)} share={0.11} color="var(--muted)" />
                    </LemonCard>
                    <LemonCard hoverEffect={false} className="p-4">
                        <h3 className="mb-2 text-xs font-semibold text-secondary">Cost per day</h3>
                        <Sparkline
                            type="bar"
                            className="h-32 w-full"
                            data={[
                                {
                                    name: 'Cost ($)',
                                    values: DAY_LABELS.map(
                                        (_, i) =>
                                            Math.round(
                                                (a.ciCost30d / 30 + daySeries(500 + a.prs30d, 0, a.ciCost30d / 40)[i]) *
                                                    10
                                            ) / 10
                                    ),
                                    color: 'brand-blue',
                                },
                            ]}
                            labels={DAY_LABELS}
                            maximumIndicator={false}
                        />
                    </LemonCard>
                </div>
                <div className="mt-2 text-[11px] text-tertiary">
                    Author pages exist for finding and explaining your own work — not for ranking people.
                </div>
            </Section>
        </div>
    )
}

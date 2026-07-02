/** Shared scaffolding for the UX-overhaul preview. One tile, one section rhythm, one header bar —
 *  the point of the redesign is that every entity page is built from exactly these pieces.
 *  Mock-only: navigation is local state (no routes), data is faked, nothing calls the API. */

import { Fragment, ReactNode, useContext, useState } from 'react'

import { LemonCard, LemonSegmentedButton, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { Lettermark } from 'lib/lemon-ui/Lettermark'
import { cn } from 'lib/utils/css-classes'

import type { MockJob, MockJobGroup, MockLogLine, MockPr } from './mockData'
import { DAY_LABELS, failedShardsLabel, groupJobs } from './mockData'
import { MockNavContext, MockRoute } from './mockNavContext'

export type { MockRoute } from './mockNavContext'

/* ============ formatting ============ */

export const fmtUsd = (x: number): string =>
    x >= 1000 ? `$${(x / 1000).toFixed(1)}k` : `$${x.toFixed(x < 20 ? 2 : 0)}`
export const fmtK = (x: number): string =>
    x >= 1000 ? `${(x / 1000).toFixed(x >= 10000 ? 0 : 1)}k` : `${Math.round(x)}`
export const fmtPct = (x: number): string => `${Math.round(x * 100)}%`
export const fmtHours = (h: number): string => (h < 48 ? `${Math.round(h)}h` : `${(h / 24).toFixed(1)}d`)
export const fmtMin = (m: number): string =>
    m < 1
        ? `${Math.round(m * 60)}s`
        : m < 60
          ? `${m < 10 ? m.toFixed(1) : Math.round(m)}m`
          : `${Math.floor(m / 60)}h ${Math.round(m % 60)}m`

/* ============ mock navigation (local state, no routes) ============ */

export function MockNavProvider({ children }: { children: ReactNode }): JSX.Element {
    const [route, setRoute] = useState<MockRoute>({ page: 'repo' })
    const go = (r: MockRoute): void => {
        setRoute(r)
        // the scene scrolls inside the app container — jump back to the top of the mock on page change
        document.querySelector('.MockUxPreview')?.scrollIntoView({ block: 'start' })
    }
    return <MockNavContext.Provider value={{ route, go }}>{children}</MockNavContext.Provider>
}

export function useMockNav(): { route: MockRoute; go: (r: MockRoute) => void } {
    return useContext(MockNavContext)
}

export function MockLink({
    to,
    children,
    className,
}: {
    to: MockRoute
    children: ReactNode
    className?: string
}): JSX.Element {
    const { go } = useMockNav()
    return (
        <Link
            className={className}
            onClick={(e) => {
                e.preventDefault()
                e.stopPropagation()
                go(to)
            }}
        >
            {children}
        </Link>
    )
}

/* ============ header bar: repo scope (once) › drill-down crumbs · branch · date ============ */

export interface CrumbItem {
    label: string
    to?: MockRoute
}

export function MockHeaderBar({
    crumbs = [],
    branch = 'master',
    range = 'Last 30 days',
    lensFilter,
    lensPickers,
}: {
    /** hierarchy below the repo (workflow › run, PR, author); empty on the repo page itself */
    crumbs?: CrumbItem[]
    branch?: string
    range?: string
    /** the lens as a literal filter — every entity page is the same runs+jobs view with this
     *  filter applied; removing it zooms out one level */
    lensFilter?: { label: string; clearTo: MockRoute }
    /** unvalued lenses shown on the repo page: clicking one opens the full list of that entity */
    lensPickers?: { label: string; to: MockRoute }[]
}): JSX.Element {
    const { go } = useMockNav()
    const chip =
        'inline-flex cursor-pointer items-center gap-1.5 rounded border border-primary bg-surface-primary px-2.5 py-1 text-xs text-secondary'
    return (
        <div className="mt-1 flex flex-wrap items-center gap-2">
            <span
                className={chip}
                title="Mock — the repo is scope picker and hierarchy root in one; click to open the repo overview"
                onClick={() => go({ page: 'repo' })}
            >
                <strong className="font-semibold text-primary">PostHog/posthog</strong>
                <span className="text-[8px] text-tertiary">▼</span>
            </span>
            {crumbs.map((c) => (
                <Fragment key={c.label}>
                    <span className="text-xs text-tertiary">›</span>
                    {c.to ? (
                        <MockLink to={c.to} className="text-[13px] font-medium">
                            {c.label}
                        </MockLink>
                    ) : (
                        <span className="text-[13px] font-semibold">{c.label}</span>
                    )}
                </Fragment>
            ))}
            <span className="ml-auto flex items-center gap-2">
                {lensPickers?.map((p) => (
                    <span
                        key={p.label}
                        className={cn(chip, 'border-dashed')}
                        title="Unvalued lens filter — click for the full list, pick a value there to focus"
                        onClick={() => go(p.to)}
                    >
                        {p.label}: <span className="text-tertiary">any</span>
                        <span className="text-[8px] text-tertiary">▼</span>
                    </span>
                ))}
                {lensFilter && (
                    <span
                        className={cn(chip, 'border-accent-highlight-secondary bg-fill-highlight-50')}
                        title="This page is the same runs+jobs view with one filter applied — remove it to zoom out"
                    >
                        <strong className="font-semibold text-primary">{lensFilter.label}</strong>
                        <span
                            className="cursor-pointer px-0.5 text-tertiary hover:text-primary"
                            onClick={(e) => {
                                e.stopPropagation()
                                go(lensFilter.clearTo)
                            }}
                        >
                            ✕
                        </span>
                    </span>
                )}
                <span className={chip} title="Mock — one branch scope for every section below">
                    branch: <strong className="font-semibold text-primary">{branch}</strong>
                    <span className="text-[8px] text-tertiary">▼</span>
                </span>
                <span className={chip} title="Mock — one date range for every section below">
                    <strong className="font-semibold text-primary">{range}</strong>
                    <span className="text-[8px] text-tertiary">▼</span>
                </span>
            </span>
        </div>
    )
}

/* ============ section rhythm ============ */

export function Section({
    id,
    title,
    note,
    right,
    children,
}: {
    id: string
    title: string
    note?: string
    right?: ReactNode
    children: ReactNode
}): JSX.Element {
    return (
        <section id={`mock-sec-${id}`} className="mb-8 mt-4 scroll-mt-14">
            <div className="mb-2 flex items-baseline gap-2.5">
                <h2 className="m-0 text-base font-semibold">{title}</h2>
                {note && <span className="text-xs text-tertiary">{note}</span>}
                {right && <span className="ml-auto text-xs">{right}</span>}
            </div>
            {children}
        </section>
    )
}

export function SectionNav({ items }: { items: { id: string; label: string }[] }): JSX.Element {
    const [active, setActive] = useState(items[0]?.id)
    return (
        <div className="sticky top-0 z-10 -mx-1 bg-primary px-1 py-2">
            <LemonSegmentedButton
                size="small"
                value={active}
                onChange={(value) => {
                    setActive(value)
                    document.getElementById(`mock-sec-${value}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                }}
                options={items.map((s) => ({ value: s.id, label: s.label }))}
            />
        </div>
    )
}

/* ============ stat tile: label · value · delta · caption · sparkline ============ */

export function DeltaBadge({
    value,
    unit = '%',
    goodWhenDown = false,
    vs = 'vs prior 30d',
}: {
    value: number
    unit?: string
    goodWhenDown?: boolean
    vs?: string
}): JSX.Element {
    if (!value) {
        return (
            <span className="text-xs font-medium text-tertiary" title={vs}>
                ±0{unit}
            </span>
        )
    }
    const up = value > 0
    const good = goodWhenDown ? !up : up
    return (
        <span
            className={cn('whitespace-nowrap text-xs font-semibold', good ? 'text-success' : 'text-danger')}
            title={vs}
        >
            {up ? '▲' : '▼'} {Math.abs(value)}
            {unit}
        </span>
    )
}

export function MockStatTile({
    label,
    value,
    valueSuffix,
    delta,
    sub,
    spark,
    badge,
}: {
    label: string
    value: string
    valueSuffix?: string
    delta?: ReactNode
    sub?: ReactNode
    spark?: number[]
    badge?: ReactNode
}): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex min-w-44 flex-1 flex-col gap-1 px-5 py-4">
            <span className="text-xs text-secondary">{label}</span>
            <span className="flex items-baseline gap-2">
                <span className="text-2xl font-semibold leading-none">{value}</span>
                {valueSuffix && <span className="text-xs font-medium text-tertiary">{valueSuffix}</span>}
                {delta}
            </span>
            {badge ? <span>{badge}</span> : <span className="min-h-4 text-xs text-tertiary">{sub}</span>}
            {spark && (
                <Sparkline
                    type="line"
                    className="mt-1 h-6 w-full"
                    data={[{ name: label, values: spark, color: 'muted' }]}
                    labels={DAY_LABELS}
                    maximumIndicator={false}
                />
            )}
        </LemonCard>
    )
}

export function PercentileBadge({ children }: { children: ReactNode }): JSX.Element {
    return (
        <span className="inline-block rounded-full bg-fill-highlight-100 px-2 py-0.5 text-[10px] font-medium text-primary">
            {children}
        </span>
    )
}

/* ============ status ============ */

export function StatusDot({ kind }: { kind: 'success' | 'danger' | 'warning' | 'muted' | 'primary' }): JSX.Element {
    const color: Record<string, string> = {
        success: 'var(--success)',
        danger: 'var(--danger)',
        warning: 'var(--warning)',
        muted: 'var(--muted)',
        primary: 'var(--brand-blue)',
    }
    return <span className="inline-block size-2 shrink-0 rounded-full" style={{ backgroundColor: color[kind] }} />
}

export function CiTag({
    ci,
}: {
    ci: 'passing' | 'failing' | 'running' | 'success' | 'failure' | 'cancelled' | 'merged' | 'open'
}): JSX.Element {
    switch (ci) {
        case 'passing':
        case 'success':
            return <LemonTag type="success">{ci === 'success' ? 'Success' : 'Passing'}</LemonTag>
        case 'failing':
        case 'failure':
            return <LemonTag type="danger">{ci === 'failure' ? 'Failure' : 'Failing'}</LemonTag>
        case 'running':
            return <LemonTag type="completion">Running</LemonTag>
        case 'cancelled':
            return <LemonTag type="muted">Cancelled</LemonTag>
        case 'merged':
            return <LemonTag type="completion">Merged</LemonTag>
        case 'open':
            return <LemonTag type="success">Open</LemonTag>
    }
}

export function AuthorChip({ handle, link = true }: { handle: string; link?: boolean }): JSX.Element {
    const inner = (
        <span className="inline-flex items-center gap-1.5">
            <Lettermark name={handle} />
            <span className="font-medium">{handle}</span>
        </span>
    )
    return link ? <MockLink to={{ page: 'author', handle }}>{inner}</MockLink> : inner
}

/* ============ logs-product-style log rows ============ */

export function LogRows({ lines, header }: { lines: MockLogLine[]; header?: ReactNode }): JSX.Element {
    const levelTag: Record<MockLogLine['level'], JSX.Element> = {
        error: (
            <LemonTag type="danger" size="small">
                ERROR
            </LemonTag>
        ),
        warn: (
            <LemonTag type="warning" size="small">
                WARN
            </LemonTag>
        ),
        info: <LemonTag size="small">INFO</LemonTag>,
        debug: (
            <LemonTag type="muted" size="small">
                DEBUG
            </LemonTag>
        ),
    }
    return (
        <div className="overflow-hidden rounded border border-primary bg-surface-primary">
            {header && (
                <div className="flex items-center gap-2 border-b border-primary px-3 py-2 text-xs font-semibold">
                    {header}
                </div>
            )}
            <table className="w-full border-collapse">
                <tbody>
                    {lines.map((l, i) => (
                        <tr key={i} className={cn(i > 0 && 'border-t border-primary')}>
                            <td className="w-20 whitespace-nowrap px-3 py-1.5 align-top font-mono text-[11px] tabular-nums text-tertiary">
                                {l.t}
                            </td>
                            <td className="w-16 px-1 py-1.5 align-top">{levelTag[l.level]}</td>
                            <td className="px-3 py-1.5 align-top font-mono text-[11.5px] leading-relaxed">{l.msg}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}

/* ============ jobs table: tight rows, subtle timing bar, queue + duration + result ============ */

export function MockJobsTable({ jobs }: { jobs: MockJob[] }): JSX.Element {
    // matrix shards collapse into one group row — 77 raw jobs become ~12 rows; failing groups first
    const groups = groupJobs(jobs).sort((a, b) => Number(b.failed.length > 0) - Number(a.failed.length > 0))
    const tmax = Math.max(...groups.map((g) => g.endMin)) * 1.05
    const barColor: Record<MockJob['conclusion'], string> = {
        success: 'var(--success)',
        failure: 'var(--danger)',
        skipped: 'var(--muted)',
    }
    return (
        <LemonTable<MockJobGroup>
            dataSource={groups}
            size="small"
            embedded
            expandable={{
                // only matrix groups expand, straight to their individual shards
                rowExpandable: (g) => (g.jobs.length > 1 ? 1 : -1),
                expandedRowRender: (g) => (
                    <div className="px-3 py-2">
                        {[...g.jobs]
                            .sort((a, b) => Number(b.conclusion === 'failure') - Number(a.conclusion === 'failure'))
                            .map((j) => (
                                <div key={j.name} className="flex items-center gap-2 py-0.5 text-[11px]">
                                    <StatusDot
                                        kind={
                                            j.conclusion === 'success'
                                                ? 'success'
                                                : j.conclusion === 'failure'
                                                  ? 'danger'
                                                  : 'muted'
                                        }
                                    />
                                    <span className="truncate font-mono">{j.name}</span>
                                    <span className="ml-auto tabular-nums text-tertiary">{fmtMin(j.durMin)}</span>
                                </div>
                            ))}
                    </div>
                ),
            }}
            columns={[
                {
                    title: 'Job',
                    render: (_, g) => (
                        <span className="overflow-hidden">
                            <span className="flex items-center gap-1.5">
                                <StatusDot
                                    kind={
                                        g.conclusion === 'success'
                                            ? 'success'
                                            : g.conclusion === 'failure'
                                              ? 'danger'
                                              : 'muted'
                                    }
                                />
                                <span className="truncate font-mono text-[11px]">{g.base}</span>
                                {g.jobs.length > 1 && (
                                    <LemonTag type="muted">
                                        ×{g.jobs.length}
                                        {g.variants > 1 ? ` · ${g.variants} variants` : ''}
                                    </LemonTag>
                                )}
                            </span>
                            {g.failed.length > 0 && (
                                <span className="mt-0.5 block pl-3.5 font-mono text-[10.5px] text-danger">
                                    {failedShardsLabel(g)} failed
                                </span>
                            )}
                        </span>
                    ),
                },
                {
                    title: 'Timing',
                    width: 220,
                    render: (_, g) => (
                        <span className="relative block h-2 w-full min-w-36">
                            <span
                                className="absolute top-[3px] h-0.5 rounded-full bg-fill-secondary"
                                style={{
                                    left: `${(g.startMin / tmax) * 100}%`,
                                    width: `${(g.queueP50Min / tmax) * 100}%`,
                                }}
                                title={`queued ~${fmtMin(g.queueP50Min)}`}
                            />
                            <span
                                className="absolute top-0.5 h-1 rounded-full opacity-80"
                                style={{
                                    left: `${((g.startMin + g.queueP50Min) / tmax) * 100}%`,
                                    width: `${Math.max(0.5, ((g.endMin - g.startMin - g.queueP50Min) / tmax) * 100)}%`,
                                    backgroundColor: barColor[g.conclusion],
                                }}
                                title={
                                    g.jobs.length > 1
                                        ? `${g.base} — ${g.jobs.length} jobs between ${fmtMin(g.minDurMin)} and ${fmtMin(g.maxDurMin)}`
                                        : `${g.base} — ${fmtMin(g.maxDurMin)} · ${g.conclusion}`
                                }
                            />
                        </span>
                    ),
                },
                {
                    title: 'Queued',
                    align: 'right',
                    render: (_, g) => <span className="tabular-nums text-tertiary">{fmtMin(g.queueP50Min)}</span>,
                },
                {
                    title: 'Duration',
                    align: 'right',
                    render: (_, g) => (
                        <span className="tabular-nums">
                            {g.jobs.length > 1 ? (
                                <>
                                    {fmtMin(g.minDurMin)} <span className="text-tertiary">→ {fmtMin(g.maxDurMin)}</span>
                                </>
                            ) : (
                                fmtMin(g.maxDurMin)
                            )}
                        </span>
                    ),
                },
                {
                    title: 'Runner',
                    render: (_, g) => <span className="font-mono text-[11px] text-tertiary">{g.jobs[0].runner}</span>,
                },
                {
                    title: 'Result',
                    render: (_, g) =>
                        g.conclusion === 'skipped' ? (
                            <LemonTag type="muted">Skipped</LemonTag>
                        ) : g.failed.length > 0 && g.jobs.length > 1 ? (
                            <LemonTag type="danger">
                                {g.failed.length}/{g.jobs.length} failed
                            </LemonTag>
                        ) : (
                            <CiTag ci={g.conclusion} />
                        ),
                },
            ]}
        />
    )
}

/* ============ job dots: a run row IS a rollup of its jobs — make that visible ============ */

export function JobDots({ jobs, max = 20 }: { jobs: MockJob[]; max?: number }): JSX.Element {
    const color: Record<MockJob['conclusion'], string> = {
        success: 'var(--success)',
        failure: 'var(--danger)',
        skipped: 'var(--muted)',
    }
    // failures always make the cut — overflow only ever hides green
    const shown =
        jobs.length > max
            ? [...jobs]
                  .sort((a, b) => Number(b.conclusion === 'failure') - Number(a.conclusion === 'failure'))
                  .slice(0, max)
            : jobs
    return (
        <span className="inline-flex items-center gap-[3px]">
            {shown.map((j) => (
                <span
                    key={j.name}
                    className="inline-block size-1.5 rounded-full"
                    style={{ backgroundColor: color[j.conclusion], opacity: j.conclusion === 'skipped' ? 0.5 : 0.9 }}
                    title={`${j.name} — ${j.conclusion}`}
                />
            ))}
            {jobs.length > max && <span className="text-[9px] text-tertiary">+{jobs.length - max}</span>}
        </span>
    )
}

/** One dot per matrix group — the readable rollup when a run has 50+ jobs. */
export function GroupDots({ groups }: { groups: MockJobGroup[] }): JSX.Element {
    const color: Record<MockJob['conclusion'], string> = {
        success: 'var(--success)',
        failure: 'var(--danger)',
        skipped: 'var(--muted)',
    }
    return (
        <span className="inline-flex items-center gap-[3px]">
            {groups.map((g) => (
                <span
                    key={g.base}
                    className="inline-block size-1.5 rounded-full"
                    style={{ backgroundColor: color[g.conclusion], opacity: g.conclusion === 'skipped' ? 0.5 : 0.9 }}
                    title={`${g.base} — ${g.jobs.length > 1 ? `${g.jobs.length} jobs, ` : ''}${g.conclusion}`}
                />
            ))}
        </span>
    )
}

/* ============ PR table: one component, same columns everywhere it appears ============ */

export function MockPrTable({ prs, showAuthor = true }: { prs: MockPr[]; showAuthor?: boolean }): JSX.Element {
    const { go } = useMockNav()
    // a State column where every row says "Open" is noise — only show it when states are mixed
    const mixedStates = new Set(prs.map((p) => p.state)).size > 1
    return (
        <LemonTable<MockPr>
            dataSource={prs}
            embedded
            onRow={(p) => ({ onClick: () => go({ page: 'pr', number: p.number }) })}
            columns={[
                {
                    title: 'Pull request',
                    render: (_, p) => (
                        <span>
                            <MockLink to={{ page: 'pr', number: p.number }}>
                                <span className="font-medium">{p.title}</span>
                            </MockLink>
                            <span className="block font-mono text-[11px] text-tertiary">#{p.number}</span>
                        </span>
                    ),
                },
                ...(showAuthor
                    ? [
                          {
                              title: 'Author',
                              render: (_: unknown, p: MockPr) => <AuthorChip handle={p.author} />,
                          },
                      ]
                    : []),
                ...(mixedStates ? [{ title: 'State', render: (_: unknown, p: MockPr) => <CiTag ci={p.state} /> }] : []),
                {
                    title: 'CI',
                    render: (_, p) => (
                        <span>
                            <CiTag ci={p.ci} />
                            {p.failingChecks && (
                                <span className="mt-0.5 block text-[10.5px] text-tertiary">{p.failingChecks}</span>
                            )}
                        </span>
                    ),
                },
                {
                    title: 'Pushes',
                    align: 'right',
                    render: (_, p) => (
                        <span className="tabular-nums">
                            {p.pushes}
                            {p.reruns > 0 && (
                                <LemonTag type="warning" className="ml-1.5">
                                    +{p.reruns}
                                </LemonTag>
                            )}
                        </span>
                    ),
                },
                {
                    title: 'CI cost',
                    align: 'right',
                    render: (_, p) => <span className="tabular-nums">{fmtUsd(p.costUsd)}</span>,
                },
                {
                    title: 'Open time',
                    align: 'right',
                    render: (_, p) => <span className="tabular-nums">{fmtHours(p.openHours)}</span>,
                },
            ]}
        />
    )
}

/* ============ entity header — identical skeleton at every level ============ */

export function MockEntityHeader({
    icon,
    title,
    titleSuffix,
    slug,
    right,
}: {
    icon?: ReactNode
    title: string
    titleSuffix?: ReactNode
    slug: ReactNode
    right?: ReactNode
}): JSX.Element {
    return (
        <div className="mt-4 flex items-start gap-3.5">
            {icon && (
                <span className="flex size-10 shrink-0 items-center justify-center rounded-lg border border-primary bg-surface-primary text-lg">
                    {icon}
                </span>
            )}
            <div className="min-w-0">
                <h1 className="m-0 text-xl font-bold leading-tight tracking-tight">
                    {title}
                    {titleSuffix && <span className="ml-2 font-normal text-tertiary">{titleSuffix}</span>}
                </h1>
                <div className="mt-0.5 flex items-center gap-2 font-mono text-[11.5px] text-tertiary">{slug}</div>
            </div>
            {right && <div className="ml-auto flex shrink-0 items-center gap-2">{right}</div>}
        </div>
    )
}

export function VerdictPill({
    kind,
    children,
}: {
    kind: 'success' | 'danger' | 'warning' | 'muted'
    children: ReactNode
}): JSX.Element {
    const cls: Record<string, string> = {
        success: 'bg-fill-success-tertiary text-success',
        danger: 'bg-fill-error-tertiary text-danger',
        warning: 'bg-fill-warning-tertiary text-warning-dark',
        muted: 'bg-fill-secondary text-secondary',
    }
    return (
        <span
            className={cn('inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold', cls[kind])}
        >
            <StatusDot
                kind={
                    kind === 'warning'
                        ? 'warning'
                        : kind === 'danger'
                          ? 'danger'
                          : kind === 'success'
                            ? 'success'
                            : 'muted'
                }
            />
            {children}
        </span>
    )
}

/* ============ share bar leaderboard row (openrouter-style) ============ */

export function ShareRow({
    rank,
    label,
    sub,
    value,
    valueSub,
    share,
    color,
    to,
    avatar,
}: {
    rank?: number
    label: ReactNode
    sub?: ReactNode
    value: ReactNode
    valueSub?: ReactNode
    share?: number
    color?: string
    to?: MockRoute
    avatar?: string
}): JSX.Element {
    const { go } = useMockNav()
    return (
        <div
            className={cn(
                'flex items-center gap-3 border-b border-primary px-1 py-2 last:border-b-0',
                to && 'cursor-pointer hover:bg-fill-button-tertiary-hover'
            )}
            onClick={to ? () => go(to) : undefined}
        >
            {rank !== undefined && (
                <span className="w-4 shrink-0 text-right text-xs tabular-nums text-tertiary">{rank}.</span>
            )}
            {avatar && <Lettermark name={avatar} />}
            <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-semibold">{label}</span>
                {sub && <span className="block truncate text-[11px] text-tertiary">{sub}</span>}
            </span>
            {share !== undefined && (
                <span className="relative h-1.5 w-40 max-w-[30%] shrink-0 overflow-hidden rounded-full bg-fill-secondary">
                    <span
                        className="absolute inset-y-0 left-0 rounded-full"
                        style={{ width: `${(share * 100).toFixed(1)}%`, backgroundColor: color ?? 'var(--brand-blue)' }}
                    />
                </span>
            )}
            <span className="shrink-0 text-right">
                <span className="block text-[13px] font-semibold tabular-nums">{value}</span>
                {valueSub && <span className="block text-[10px] text-tertiary">{valueSub}</span>}
            </span>
        </div>
    )
}

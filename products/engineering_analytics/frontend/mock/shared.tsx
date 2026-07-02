/** Shared scaffolding for the UX-overhaul preview. One tile, one section rhythm, one lens path —
 *  the point of the redesign is that every entity page is built from exactly these pieces.
 *  Mock-only: navigation is local state (no routes), data is faked, nothing calls the API. */

import { ReactNode, useContext, useState } from 'react'

import { LemonCard, LemonTag, Link } from '@posthog/lemon-ui'

import { Lettermark } from 'lib/lemon-ui/Lettermark'
import { cn } from 'lib/utils/css-classes'

import type { MockJob, MockLogLine } from './mockData'
import { DAY_LABELS } from './mockData'
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

/* ============ lens path (the signature: one focus stack, every page) ============ */

export interface LensItem {
    level: string
    label: string
    to?: MockRoute
    current?: boolean
}

export function LensPath({ items }: { items: LensItem[] }): JSX.Element {
    return (
        <div className="flex flex-wrap items-end gap-0 pt-1">
            {items.map((it, i) => (
                <div key={it.level + it.label} className="flex items-end">
                    {i > 0 && <span className="px-2 pb-1.5 text-xs text-tertiary">›</span>}
                    <div className="flex flex-col gap-0.5">
                        <span className="pl-2.5 text-[9px] font-semibold uppercase tracking-widest text-tertiary">
                            {it.level}
                        </span>
                        <span
                            className={cn(
                                'inline-flex items-center rounded border px-2.5 py-1 text-xs',
                                it.current
                                    ? 'border-accent font-semibold text-primary'
                                    : 'border-primary bg-surface-primary text-secondary'
                            )}
                        >
                            {it.to && !it.current ? <MockLink to={it.to}>{it.label}</MockLink> : it.label}
                        </span>
                    </div>
                </div>
            ))}
        </div>
    )
}

/* ============ scope bar — identical on every page, that's the point ============ */

export function MockScopeBar({
    branch = 'master',
    range = 'Last 30 days',
}: {
    branch?: string
    range?: string
}): JSX.Element {
    const chip =
        'inline-flex cursor-pointer items-center gap-1.5 rounded border border-primary bg-surface-primary px-2.5 py-1 text-xs text-secondary'
    return (
        <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className={chip} title="Mock — picks the GitHub source / repo">
                <strong className="font-semibold text-primary">PostHog/posthog</strong>
                <span className="text-[8px] text-tertiary">▼</span>
            </span>
            <span
                className={cn(chip, 'border-accent-highlight-secondary bg-fill-highlight-50')}
                title="Mock — one branch scope for every section below"
            >
                branch: <strong className="font-semibold text-primary">{branch}</strong>
                <span className="text-[8px] text-tertiary">▼</span>
            </span>
            <span className={chip} title="Mock — one date range for every section below">
                <strong className="font-semibold text-primary">{range}</strong>
                <span className="text-[8px] text-tertiary">▼</span>
            </span>
            <span className="ml-auto text-xs text-tertiary">
                One scope, every section — filters never differ per tab
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
    return (
        <nav className="sticky top-0 z-10 -mx-1 flex gap-0.5 bg-primary px-1 py-2">
            {items.map((s) => (
                <button
                    key={s.id}
                    type="button"
                    className="cursor-pointer rounded border-none bg-transparent px-3 py-1 text-xs font-medium text-secondary hover:bg-fill-button-tertiary-hover"
                    onClick={() =>
                        document
                            .getElementById(`mock-sec-${s.id}`)
                            ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                    }
                >
                    {s.label}
                </button>
            ))}
        </nav>
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

export function TileSparkline({
    points,
    accent = 'var(--accent)',
}: {
    points: number[]
    accent?: string
}): JSX.Element {
    const w = 64
    const h = 26
    const mn = Math.min(...points)
    const mx = Math.max(...points)
    const rg = mx - mn || 1
    const X = (i: number): number => 1 + (i / (points.length - 1)) * (w - 2)
    const Y = (v: number): number => h - 3 - ((v - mn) / rg) * (h - 6)
    const d = points.map((v, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)} ${Y(v).toFixed(1)}`).join(' ')
    const li = points.length - 1
    return (
        <svg width={w} height={h} aria-hidden="true" className="shrink-0">
            <path
                d={d}
                fill="none"
                stroke="var(--border-primary)"
                strokeWidth={1.5}
                strokeLinecap="round"
                strokeLinejoin="round"
            />
            <path
                d={`M${X(li - 1).toFixed(1)} ${Y(points[li - 1]).toFixed(1)} L${X(li).toFixed(1)} ${Y(points[li]).toFixed(1)}`}
                fill="none"
                stroke={accent}
                strokeWidth={1.5}
                strokeLinecap="round"
            />
            <circle
                cx={X(li)}
                cy={Y(points[li])}
                r={2.5}
                fill={accent}
                stroke="var(--bg-surface-primary)"
                strokeWidth={1.5}
            />
        </svg>
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
        <LemonCard hoverEffect={false} className="relative flex min-w-44 flex-1 flex-col gap-1 px-5 py-4">
            <span className="text-xs text-secondary">{label}</span>
            <span className="flex items-baseline gap-2">
                <span className="text-2xl font-semibold leading-none">{value}</span>
                {valueSuffix && <span className="text-xs font-medium text-tertiary">{valueSuffix}</span>}
                {delta}
            </span>
            {badge ? <span>{badge}</span> : <span className="min-h-4 text-xs text-tertiary">{sub}</span>}
            {spark && (
                <span className="absolute bottom-2.5 right-3">
                    <TileSparkline points={spark} />
                </span>
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

/* ============ jobs gantt: queue (hollow) then execution (filled), per job ============ */

export function JobsGantt({ jobs }: { jobs: MockJob[] }): JSX.Element {
    const tmax = Math.max(...jobs.map((j) => j.startMin + j.queueMin + j.durMin)) * 1.05
    const color: Record<MockJob['conclusion'], string> = {
        success: 'var(--success)',
        failure: 'var(--danger)',
        skipped: 'var(--muted)',
    }
    return (
        <div className="flex flex-col gap-1">
            {jobs.map((j) => (
                <div key={j.name} className="grid grid-cols-[230px_1fr_64px] items-center gap-2.5 text-xs">
                    <span className="flex items-center gap-1.5 overflow-hidden">
                        <StatusDot
                            kind={
                                j.conclusion === 'success' ? 'success' : j.conclusion === 'failure' ? 'danger' : 'muted'
                            }
                        />
                        <span className="truncate font-mono text-[11px]">{j.name}</span>
                    </span>
                    <span className="relative h-3.5">
                        <span
                            className="absolute top-[3px] h-2 rounded-sm border border-primary bg-fill-secondary"
                            style={{ left: `${(j.startMin / tmax) * 100}%`, width: `${(j.queueMin / tmax) * 100}%` }}
                            title={`queued ${fmtMin(j.queueMin)}`}
                        />
                        <span
                            className="absolute top-px h-3 rounded"
                            style={{
                                left: `${((j.startMin + j.queueMin) / tmax) * 100}%`,
                                width: `${(j.durMin / tmax) * 100}%`,
                                backgroundColor: color[j.conclusion],
                            }}
                            title={`${j.name} — ${fmtMin(j.durMin)} · ${j.conclusion}`}
                        />
                    </span>
                    <span className="text-right text-[11px] tabular-nums text-secondary">{fmtMin(j.durMin)}</span>
                </div>
            ))}
            <div className="mt-2 flex gap-4 text-[11px] text-secondary">
                <span className="inline-flex items-center gap-1.5">
                    <span className="inline-block h-2 w-3 rounded-sm border border-primary bg-fill-secondary" /> Queued
                </span>
                <span className="inline-flex items-center gap-1.5">
                    <span className="inline-block size-2.5 rounded-sm" style={{ background: 'var(--success)' }} />{' '}
                    Succeeded
                </span>
                <span className="inline-flex items-center gap-1.5">
                    <span className="inline-block size-2.5 rounded-sm" style={{ background: 'var(--danger)' }} /> Failed
                </span>
                <span className="inline-flex items-center gap-1.5">
                    <span className="inline-block size-2.5 rounded-sm" style={{ background: 'var(--muted)' }} /> Skipped
                </span>
            </div>
        </div>
    )
}

/* ============ small charts (svg, mock-grade) ============ */

export interface LineSeriesSpec {
    name: string
    pts: number[]
    color: string
    fill?: boolean
}

export function LineChartSvg({
    series,
    yFmt = (v) => `${Math.round(v)}`,
    yMin = null,
    yMax = null,
    height = 180,
}: {
    series: LineSeriesSpec[]
    yFmt?: (v: number) => string
    yMin?: number | null
    yMax?: number | null
    height?: number
}): JSX.Element {
    const w = 520
    const h = height
    const padL = 40
    const padR = 12
    const padT = 10
    const padB = 22
    const all = series.flatMap((s) => s.pts)
    let mn = yMin ?? Math.min(...all)
    let mx = yMax ?? Math.max(...all)
    if (mx === mn) {
        mx = mn + 1
    }
    const X = (i: number): number => padL + (i / (DAY_LABELS.length - 1)) * (w - padL - padR)
    const Y = (v: number): number => padT + (1 - (v - mn) / (mx - mn)) * (h - padT - padB)
    return (
        <svg viewBox={`0 0 ${w} ${h}`} width="100%" style={{ maxWidth: 620 }} role="img">
            {[0, 1, 2, 3, 4].map((t) => {
                const v = mn + ((mx - mn) * t) / 4
                return (
                    <g key={t}>
                        <line
                            x1={padL}
                            x2={w - padR}
                            y1={Y(v)}
                            y2={Y(v)}
                            stroke="var(--border-primary)"
                            strokeWidth={1}
                        />
                        <text x={padL - 6} y={Y(v) + 3} textAnchor="end" fontSize={10} fill="var(--text-tertiary)">
                            {yFmt(v)}
                        </text>
                    </g>
                )
            })}
            {DAY_LABELS.map((l, i) =>
                i % 3 === 0 || i === DAY_LABELS.length - 1 ? (
                    <text key={l} x={X(i)} y={h - 6} textAnchor="middle" fontSize={10} fill="var(--text-tertiary)">
                        {l}
                    </text>
                ) : null
            )}
            {series.map((s) => {
                const d = s.pts.map((v, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)} ${Y(v).toFixed(1)}`).join(' ')
                const last = s.pts[s.pts.length - 1]
                return (
                    <g key={s.name}>
                        {s.fill && (
                            <path
                                d={`${d} L${X(s.pts.length - 1)} ${Y(mn)} L${X(0)} ${Y(mn)} Z`}
                                fill={s.color}
                                opacity={0.08}
                            />
                        )}
                        <path
                            d={d}
                            fill="none"
                            stroke={s.color}
                            strokeWidth={2}
                            strokeLinecap="round"
                            strokeLinejoin="round"
                        >
                            <title>{s.name}</title>
                        </path>
                        <circle
                            cx={X(s.pts.length - 1)}
                            cy={Y(last)}
                            r={3.5}
                            fill={s.color}
                            stroke="var(--bg-surface-primary)"
                            strokeWidth={2}
                        />
                    </g>
                )
            })}
        </svg>
    )
}

export function StackedColumnsSvg({
    data,
    keys,
    colors,
    yFmt = fmtK,
    height = 170,
}: {
    data: Record<string, number>[]
    keys: string[]
    colors: string[]
    yFmt?: (v: number) => string
    height?: number
}): JSX.Element {
    const w = 520
    const h = height
    const padL = 38
    const padR = 8
    const padT = 8
    const padB = 22
    const totals = data.map((d) => keys.reduce((a, k) => a + d[k], 0))
    const mx = Math.max(...totals) || 1
    const bw = Math.min(24, (w - padL - padR) / data.length - 6)
    const X = (i: number): number => padL + ((i + 0.5) / data.length) * (w - padL - padR) - bw / 2
    const H = (v: number): number => (v / mx) * (h - padT - padB)
    return (
        <svg viewBox={`0 0 ${w} ${h}`} width="100%" style={{ maxWidth: 620 }} role="img">
            {[0, 1, 2, 3].map((t) => {
                const v = (mx * t) / 3
                const y = h - padB - H(v)
                return (
                    <g key={t}>
                        <line x1={padL} x2={w - padR} y1={y} y2={y} stroke="var(--border-primary)" strokeWidth={1} />
                        <text x={padL - 6} y={y + 3} textAnchor="end" fontSize={10} fill="var(--text-tertiary)">
                            {yFmt(v)}
                        </text>
                    </g>
                )
            })}
            {DAY_LABELS.map((l, i) =>
                i % 3 === 0 || i === DAY_LABELS.length - 1 ? (
                    <text
                        key={l}
                        x={X(i) + bw / 2}
                        y={h - 6}
                        textAnchor="middle"
                        fontSize={10}
                        fill="var(--text-tertiary)"
                    >
                        {l}
                    </text>
                ) : null
            )}
            {data.map((d, i) => {
                let y = h - padB
                const segs = keys.map((k, ki) => {
                    const bh = H(d[k])
                    y -= bh
                    return { k, ki, bh, y }
                })
                const title = `${DAY_LABELS[i]} — ${keys.map((k) => `${k}: ${yFmt(d[k])}`).join(', ')}`
                return (
                    <g key={i}>
                        {segs.map(
                            (s) =>
                                s.bh > 0.5 && (
                                    <rect
                                        key={s.k}
                                        x={X(i)}
                                        y={s.y}
                                        width={bw}
                                        // 2px surface gap between stacked segments
                                        height={Math.max(1, s.bh - 2)}
                                        rx={s.ki === segs.filter((g) => g.bh > 0.5).length - 1 ? 3 : 1}
                                        fill={colors[s.ki]}
                                    />
                                )
                        )}
                        <rect x={X(i) - 3} y={padT} width={bw + 6} height={h - padT - padB} fill="transparent">
                            <title>{title}</title>
                        </rect>
                    </g>
                )
            })}
        </svg>
    )
}

export function ChartLegend({ items }: { items: { label: string; color: string; line?: boolean }[] }): JSX.Element {
    return (
        <div className="mt-2 flex flex-wrap gap-3.5 text-[11px] text-secondary">
            {items.map((it) => (
                <span key={it.label} className="inline-flex items-center gap-1.5">
                    <span
                        className={cn('inline-block', it.line ? 'h-0.5 w-3.5 rounded' : 'size-2.5 rounded-sm')}
                        style={{ backgroundColor: it.color }}
                    />
                    {it.label}
                </span>
            ))}
        </div>
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

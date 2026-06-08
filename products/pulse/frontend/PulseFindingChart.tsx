import clsx from 'clsx'
import { useState } from 'react'

import { IconFlag, IconFlask, IconNotebook } from '@posthog/icons'
import { LemonTag, Link, Popover } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTagType } from 'lib/lemon-ui/LemonTag'

import { PulseTimelineMarker } from './pulseTypes'

interface SignalMeta {
    icon: JSX.Element
    tagType: LemonTagType
    label: string
}

// Distinct colour + icon per change type, kept apart from the red/green the line uses for metric direction.
const SIGNAL_META: Record<string, SignalMeta> = {
    feature_flag: { icon: <IconFlag />, tagType: 'warning', label: 'Feature flag' },
    experiment: { icon: <IconFlask />, tagType: 'highlight', label: 'Experiment' },
    annotation: { icon: <IconNotebook />, tagType: 'primary', label: 'Annotation' },
}
const FALLBACK_META: SignalMeta = { icon: <IconNotebook />, tagType: 'default', label: 'Change' }

const TONE_TEXT: Record<string, string> = {
    danger: 'text-danger',
    success: 'text-success',
    muted: 'text-muted',
}

// Markers closer than this (fraction of the axis width) would overlap, so they collapse into one cluster
// chip you click through to the individual changes.
const MIN_MARKER_GAP = 0.05

function metaFor(type: string): SignalMeta {
    return SIGNAL_META[type] ?? FALLBACK_META
}

type ChartItem =
    | { kind: 'marker'; key: string; position: number; marker: PulseTimelineMarker }
    | { kind: 'cluster'; key: string; position: number; markers: PulseTimelineMarker[] }

function MarkerDetails({ marker }: { marker: PulseTimelineMarker }): JSX.Element {
    const meta = metaFor(marker.type)
    return (
        <div className="flex flex-col gap-1 p-2 max-w-xs">
            <span className="text-xs uppercase font-medium text-muted">
                {meta.label}
                {marker.change ? ` · ${marker.change}` : ''}
            </span>
            <span className="font-semibold">{marker.label}</span>
            <span className="text-xs text-muted">{dayjs(marker.timestamp).format('ddd, MMM D')}</span>
            {marker.to ? (
                <LemonButton type="secondary" size="xsmall" to={marker.to} targetBlank className="mt-1 self-start">
                    Open {meta.label.toLowerCase()}
                </LemonButton>
            ) : null}
        </div>
    )
}

function ClusterDetails({ markers }: { markers: PulseTimelineMarker[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-1.5 p-2 max-w-sm">
            <span className="text-xs uppercase font-medium text-muted">
                {markers.length} changes on {dayjs(markers[0].timestamp).format('MMM D')}
            </span>
            {markers.map((marker) => {
                const meta = metaFor(marker.type)
                return (
                    <div key={marker.key} className="flex items-start gap-1.5 text-sm">
                        {/* items-start + a nudge keeps the icon aligned to the first line of a wrapped label */}
                        <span className="shrink-0 mt-0.5">{meta.icon}</span>
                        <span className="min-w-0">
                            {marker.to ? (
                                <Link to={marker.to} target="_blank">
                                    {marker.label}
                                </Link>
                            ) : (
                                marker.label
                            )}
                            {/* the action verb — e.g. "turned on" / "launched" — so a toggle is visible here too */}
                            {marker.change ? <span className="text-muted"> · {marker.change}</span> : null}
                        </span>
                    </div>
                )
            })}
        </div>
    )
}

// One marker pinned to the bottom bar with a guide line rising to the time it happened. Click opens a
// popover (not a hover tooltip — that was unreadable/unclickable) with the details and a deep link.
function ChartMarker({ item }: { item: ChartItem }): JSX.Element {
    const [open, setOpen] = useState(false)
    const tag =
        item.kind === 'cluster' ? (
            <LemonTag type="muted" size="small">
                {item.markers.length}
            </LemonTag>
        ) : (
            <LemonTag type={metaFor(item.marker.type).tagType} size="small" icon={metaFor(item.marker.type).icon}>
                {null}
            </LemonTag>
        )
    return (
        <div
            className="absolute inset-y-0 -translate-x-1/2 flex flex-col items-center"
            style={{ left: `${item.position * 100}%` }}
        >
            <div className="w-px flex-1 bg-border" />
            <Popover
                visible={open}
                onClickOutside={() => setOpen(false)}
                placement="top"
                overlay={
                    item.kind === 'cluster' ? (
                        <ClusterDetails markers={item.markers} />
                    ) : (
                        <MarkerDetails marker={item.marker} />
                    )
                }
            >
                <span role="button" tabIndex={0} className="cursor-pointer shrink-0" onClick={() => setOpen((v) => !v)}>
                    {tag}
                </span>
            </Popover>
        </div>
    )
}

// The finding's metric trend as a line, with its referenced flag / experiment / annotation changes overlaid
// as vertical guide lines dropping from when they happened to an icon on the bottom bar — so the move and
// the changes that might explain it (a coincidence to check, never proven cause) read together. Same-day
// markers beyond MAX_MARKERS_PER_DAY converge into one chip. The line renders whenever there are >= 2 points.
export function PulseFindingChart({
    series,
    markers,
    axisStart,
    axisEnd,
    tone,
}: {
    series: number[]
    markers: PulseTimelineMarker[]
    axisStart: string
    axisEnd: string
    tone: 'danger' | 'success' | 'muted'
}): JSX.Element | null {
    if (series.length < 2) {
        return null
    }

    const min = Math.min(...series)
    const max = Math.max(...series)
    const range = max - min || 1
    // viewBox is 0..100 in both axes with preserveAspectRatio="none", so points map straight to the box.
    const linePoints = series
        .map((value, index) => {
            const x = (index / (series.length - 1)) * 100
            const y = 100 - ((value - min) / range) * 100
            return `${x.toFixed(2)},${y.toFixed(2)}`
        })
        .join(' ')

    // Collapse markers that sit closer than MIN_MARKER_GAP (they'd overlap) into one cluster. markers
    // arrive sorted by position, so a greedy left-to-right sweep groups each run of near-adjacent ones.
    const items: ChartItem[] = []
    let group: PulseTimelineMarker[] = []
    const flush = (): void => {
        if (group.length === 1) {
            items.push({ kind: 'marker', key: group[0].key, position: group[0].position, marker: group[0] })
        } else if (group.length > 1) {
            const position = group.reduce((sum, m) => sum + m.position, 0) / group.length
            items.push({ kind: 'cluster', key: `cluster-${group[0].key}`, position, markers: [...group] })
        }
        group = []
    }
    for (const marker of markers) {
        if (group.length && marker.position - group[group.length - 1].position > MIN_MARKER_GAP) {
            flush()
        }
        group.push(marker)
    }
    flush()

    return (
        <div className="mt-1">
            <div className="text-muted-alt text-xs mb-1">
                {markers.length ? 'Trend & related changes' : 'Recent trend'}
            </div>
            {/* Dynamic left% / SVG point coords are data-driven, so inline positioning is unavoidable here.
                The line lives in the top band; markers sit in the strip below it so they never cross the line. */}
            <div className="relative h-20 w-full">
                <svg
                    viewBox="0 0 100 100"
                    preserveAspectRatio="none"
                    className={clsx('absolute inset-x-0 top-0 h-12 w-full overflow-visible', TONE_TEXT[tone])}
                >
                    <polyline
                        points={linePoints}
                        fill="none"
                        stroke="currentColor"
                        strokeWidth={1.5}
                        strokeLinejoin="round"
                        strokeLinecap="round"
                        vectorEffect="non-scaling-stroke"
                    />
                </svg>
                {items.map((item) => (
                    <ChartMarker key={item.key} item={item} />
                ))}
            </div>
            <div className="flex justify-between text-muted-alt text-[10px] mt-0.5">
                <span>{dayjs(axisStart).format('MMM D')}</span>
                <span>{dayjs(axisEnd).format('MMM D')}</span>
            </div>
        </div>
    )
}

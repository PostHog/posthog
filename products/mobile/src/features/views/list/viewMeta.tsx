import type { ReactElement } from 'react'

import { calendarDaysBetween, formatMonthDay } from '@/lib/dates'
import { formatMetricValue } from '@/model/adapters/metric'
import type { MetricFormat } from '@/model/types'
import type { NumberDelta, PinDisplayMode, ViewEntry, ViewKind, ViewRef } from '@/model/views'
import { CanvasIcon } from '@/ui/icons/CanvasIcon'
import { DashboardIcon } from '@/ui/icons/DashboardIcon'
import { DocumentIcon } from '@/ui/icons/DocumentIcon'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { GlobeIcon } from '@/ui/icons/GlobeIcon'
import { LineChartIcon } from '@/ui/icons/LineChartIcon'
import { colors } from '@/ui/tokens'

import type { PinTarget } from '../shortcutInput'

const TYPE_LABEL: Record<ViewKind, string | null> = {
    dashboard: 'Dashboard',
    insight: 'Insight',
    web_analytics: 'Web analytics',
    notebook: 'Notebook',
    canvas: 'Canvas',
    web_link: null,
}

export function viewTypeLabel(kind: ViewKind): string | null {
    return TYPE_LABEL[kind]
}

interface ViewIconProps {
    kind: ViewKind
    size?: number
    color?: string
}

export function ViewIcon({ kind, size = 18, color = colors.muted }: ViewIconProps): ReactElement {
    switch (kind) {
        case 'dashboard':
            return <DashboardIcon size={size} color={color} />
        case 'insight':
            return <LineChartIcon size={size} color={color} />
        case 'web_analytics':
            return <GlobeIcon size={size} color={color} />
        case 'notebook':
            return <DocumentIcon size={size} color={color} />
        case 'canvas':
            return <CanvasIcon size={size} color={color} />
        case 'web_link':
            return <ExternalLinkIcon size={size} color={color} />
    }
}

/** The app route of a native view. The other kinds open on the web. */
export function viewHref(view: Pick<ViewRef, 'kind' | 'ref'>, entry: ViewEntry, mode?: PinDisplayMode): string | null {
    const query = `?from=${entry}${mode ? `&mode=${mode}` : ''}`
    switch (view.kind) {
        case 'dashboard':
            return view.ref ? `/views/dashboard/${encodeURIComponent(view.ref)}${query}` : null
        case 'insight':
            return view.ref ? `/views/insight/${encodeURIComponent(view.ref)}${query}` : null
        case 'web_analytics':
            return `/views/web-analytics${query}`
        default:
            return null
    }
}

/** What the phone writes to pin a view. Null for kinds only the web can pin. */
export function pinTargetFor(view: Pick<ViewRef, 'kind' | 'ref' | 'name'>): PinTarget | null {
    switch (view.kind) {
        case 'dashboard': {
            if (!view.ref) {
                return null
            }
            const id = Number(view.ref)
            return { kind: 'dashboard', id: Number.isInteger(id) ? id : view.ref, name: view.name }
        }
        case 'insight':
            return view.ref ? { kind: 'insight', shortId: view.ref, name: view.name } : null
        case 'web_analytics':
            return { kind: 'web_analytics' }
        default:
            return null
    }
}

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

/** "2 h ago", "yesterday", "3 days ago", "last week", or the date. */
export function relativeDay(iso: string, now: Date): string {
    const at = new Date(iso)
    const diff = now.getTime() - at.getTime()
    if (!Number.isFinite(diff)) {
        return ''
    }
    if (diff < MINUTE) {
        return 'just now'
    }
    if (diff < HOUR) {
        return `${Math.floor(diff / MINUTE)} min ago`
    }
    const days = calendarDaysBetween(at, now)
    if (days <= 0 || diff < 12 * HOUR) {
        return `${Math.floor(diff / HOUR)} h ago`
    }
    if (days === 1) {
        return 'yesterday'
    }
    if (days < 7) {
        return `${days} days ago`
    }
    if (diff < 14 * DAY) {
        return 'last week'
    }
    return formatMonthDay(at)
}

export interface DeltaText {
    text: string
    direction: 'up' | 'down' | 'flat'
    /** Spoken text, such as "Down 5.7% from the previous period". */
    label: string
}

const MINUS = '−'

function signed(value: number, text: string): string {
    return value > 0 ? `+${text}` : value < 0 ? `${MINUS}${text}` : text
}

/** The neutral change pill: the app cannot tell whether up is good for a metric someone else built. */
export function deltaText(delta: NumberDelta, format: MetricFormat): DeltaText {
    let text: string
    let size: number
    if (delta.unit === 'points') {
        size = Math.round(delta.change * 10) / 10
        text = signed(size, `${Math.abs(size).toFixed(1)} pts`)
    } else if (delta.percent !== null) {
        size = Math.round(delta.percent * 10) / 10
        const magnitude = Math.abs(size)
        text = signed(size, `${magnitude >= 10 ? Math.round(magnitude) : magnitude.toFixed(1)}%`)
    } else {
        size = delta.change
        text = signed(size, formatMetricValue(Math.abs(size), format.valueFormat, format.unit))
    }
    const direction = size > 0 ? 'up' : size < 0 ? 'down' : 'flat'
    const against =
        delta.basis === 'compare' || !delta.previousAt
            ? 'from the previous period'
            : `from ${formatMonthDay(new Date(delta.previousAt))}`
    const spoken = direction === 'flat' ? 'No change' : `${direction === 'up' ? 'Up' : 'Down'} ${text.slice(1)}`
    return { text: direction === 'flat' ? 'No change' : text, direction, label: `${spoken} ${against}` }
}

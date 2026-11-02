import type { ReactElement } from 'react'

import { calendarDaysBetween, formatMonthDay } from '@/lib/dates'
import type { ViewKind, ViewRef } from '@/model/views'
import { CanvasIcon } from '@/ui/icons/CanvasIcon'
import { DashboardIcon } from '@/ui/icons/DashboardIcon'
import { DocumentIcon } from '@/ui/icons/DocumentIcon'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { GlobeIcon } from '@/ui/icons/GlobeIcon'
import { LineChartIcon } from '@/ui/icons/LineChartIcon'
import { useColors } from '@/ui/theme'

import type { PinTarget } from '../shortcutInput'

const TYPE_LABEL: Record<ViewKind, string | null> = {
    dashboard: 'Dashboard',
    insight: 'Insight',
    // The view's name is already "Web analytics", so its second line says what kind of view it is.
    web_analytics: 'Built-in view',
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

export function ViewIcon({ kind, size = 18, color: colorProp }: ViewIconProps): ReactElement {
    const colors = useColors()
    const color = colorProp ?? colors.muted
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

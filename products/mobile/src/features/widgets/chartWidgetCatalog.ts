import { tileLimitReason } from '@/features/views/list/tileEligibility'
import { capabilitiesOf, queryKindOf, tileShapeOf } from '@/model/adapters/insightSnapshot'
import type { PinKind, PinView } from '@/model/views'

// The pin catalog the Chart home screen widget offers in its OS picker. The JSON shape is a contract with the native
// widgets: see modules/chart-widget/README.md before changing a field.

/** The OS pickers list at most this many pins, in Views order, and a sync reads metadata for at most this many. */
export const CATALOG_PIN_LIMIT = 30

export interface WidgetPinInsight {
    insightId: number
    shortId: string
    name: string
    query: unknown
}

export interface WidgetCatalogPin {
    /** The pin's `shortcutId`, which the widget configuration stores. */
    id: string
    kind: PinKind
    name: string
    subtitle: string
    /** Null until the app has read the insight; the widget then reads by `shortId`. */
    insightId: number | null
    shortId: string | null
    /** The dashboard's numeric id, sent as `from_dashboard`. Null for an insight pin. */
    dashboardId: number | null
    eligible: boolean
    number: boolean
    chart: boolean
    reason: string | null
}

export interface WidgetCatalogProject {
    host: string
    projectId: number
    projectName: string
}

/** The catalog without `writtenAt`, so two syncs of the same pins compare equal. */
export interface WidgetCatalogBody extends WidgetCatalogProject {
    version: 1
    pins: WidgetCatalogPin[]
}

export const PICK_TILE_REASON = 'Choose a tile in Views first'
export const UNREAD_REASON = 'Open it in Views first'
export const SQL_REASON = 'Not supported on the widget yet'
export const MISSING_REASON = "Couldn't find this insight"

export function pinInsightShortId(pin: PinView): string | null {
    if (pin.kind === 'insight') {
        return pin.ref
    }
    return typeof pin.display.insightId === 'number' ? (pin.display.insightShortId ?? null) : null
}

function dashboardIdOf(pin: PinView): number | null {
    if (pin.kind !== 'dashboard') {
        return null
    }
    const id = Number(pin.ref)
    return Number.isInteger(id) ? id : null
}

type Eligibility = Pick<WidgetCatalogPin, 'eligible' | 'number' | 'chart' | 'reason'>

function ineligible(reason: string): Eligibility {
    return { eligible: false, number: false, chart: false, reason }
}

// Only trends insights are offered, because the widgets parse a trends response only.
function eligibilityOf(query: unknown): Eligibility {
    const kind = queryKindOf(query)
    if (kind === 'HogQLQuery') {
        return ineligible(SQL_REASON)
    }
    if (kind !== 'TrendsQuery') {
        return ineligible(tileLimitReason({ kind: 'insight', seriesCount: 0, hasBreakdown: false }, 'chart'))
    }
    const { number, chart } = capabilitiesOf(query)
    if (!number && !chart) {
        return ineligible(tileLimitReason({ kind: 'insight', ...tileShapeOf(query) }, 'chart'))
    }
    return { eligible: true, number, chart, reason: null }
}

/** Keyed by `short_id`. Null: the server no longer returns the insight. Missing: the app has not read it yet. */
export type WidgetPinMetadata = ReadonlyMap<string, WidgetPinInsight | null>

function catalogPin(pin: PinView, metadata: WidgetPinMetadata): WidgetCatalogPin {
    const shortId = pinInsightShortId(pin)
    const insight = shortId ? metadata.get(shortId) : undefined
    const base = {
        id: pin.shortcutId,
        kind: pin.kind,
        name: pin.name,
        subtitle: pin.kind === 'insight' ? 'Insight' : insight ? `${pin.name} · ${insight.name}` : 'Dashboard',
        insightId: insight?.insightId ?? pin.display.insightId ?? null,
        shortId,
        dashboardId: dashboardIdOf(pin),
    }
    if (pin.kind === 'dashboard' && typeof pin.display.insightId !== 'number') {
        return { ...base, ...ineligible(PICK_TILE_REASON) }
    }
    if (insight === null) {
        return { ...base, ...ineligible(MISSING_REASON) }
    }
    if (!insight) {
        return { ...base, ...ineligible(UNREAD_REASON) }
    }
    return { ...base, ...eligibilityOf(insight.query) }
}

export function buildCatalog(
    pins: readonly PinView[],
    metadata: WidgetPinMetadata,
    project: WidgetCatalogProject
): WidgetCatalogBody {
    return {
        version: 1,
        host: project.host,
        projectId: project.projectId,
        projectName: project.projectName,
        pins: pins.slice(0, CATALOG_PIN_LIMIT).map((pin) => catalogPin(pin, metadata)),
    }
}

/** The JSON the native module stores: the body with `writtenAt` before `pins`, as the contract lists the fields. */
export function catalogJson(body: WidgetCatalogBody, writtenAt: number): string {
    const { pins, ...head } = body
    return JSON.stringify({ ...head, writtenAt, pins })
}

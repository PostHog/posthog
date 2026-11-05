import { SHORTCUT_PAGE_SIZE } from '@/api/shortcuts'
import { capabilitiesOf, queryKindOf } from '@/model/adapters/insightSnapshot'
import type { InsightSnapshot, PinKind, PinView } from '@/model/views'

import { type WidgetSnapshot, widgetSnapshot } from './chartWidgetSnapshot'

// The pin catalog the Chart home screen widget offers in its OS picker. The JSON shape is a contract with the native
// widgets: see modules/chart-widget/README.md before changing a field.

/** The OS pickers list at most this many pins, in Views order, and a sync reads metadata for at most this many. */
export const CATALOG_PIN_LIMIT = SHORTCUT_PAGE_SIZE

export interface WidgetPinInsight {
    insightId: number
    shortId: string
    name: string
    query: unknown
    snapshot?: InsightSnapshot
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
    displayMode: PinView['display']['mode']
    snapshot?: WidgetSnapshot
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
export const MISSING_REASON = "Couldn't find this insight"

export function pinInsightShortId(pin: PinView): string | null {
    if (pin.kind === 'insight') {
        return pin.ref
    }
    return typeof pin.display.insightId === 'number'
        ? (pin.display.insightShortId ?? `#${pin.display.insightId}`)
        : null
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

function eligibilityOf(insight: WidgetPinInsight): Eligibility {
    if (!queryKindOf(insight.query)) {
        return ineligible(UNREAD_REASON)
    }
    const capabilities = insight.snapshot?.capabilities ?? capabilitiesOf(insight.query)
    return { eligible: true, number: capabilities.number, chart: capabilities.chart, reason: null }
}

/** Keyed by pin id (or `short_id` for callers without a pin context). Null: the server no longer returns the insight. Missing: the app has not read it yet. */
export type WidgetPinMetadata = ReadonlyMap<string, WidgetPinInsight | null>

function catalogPin(pin: PinView, metadata: WidgetPinMetadata, includeSnapshot: boolean): WidgetCatalogPin {
    const shortId = pinInsightShortId(pin)
    const insight = metadata.has(pin.shortcutId)
        ? metadata.get(pin.shortcutId)
        : shortId
          ? metadata.get(shortId)
          : undefined
    const snapshot =
        includeSnapshot && insight?.snapshot ? widgetSnapshot(pin.shortcutId, insight.snapshot, pin.display.mode) : null
    const base = {
        id: pin.shortcutId,
        kind: pin.kind,
        name: pin.name,
        subtitle: pin.kind === 'insight' ? 'Insight' : insight ? `${pin.name} · ${insight.name}` : 'Dashboard',
        insightId: insight?.insightId ?? pin.display.insightId ?? null,
        shortId: insight?.shortId ?? shortId,
        dashboardId: dashboardIdOf(pin),
        displayMode: pin.display.mode,
        ...(snapshot ? { snapshot } : {}),
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
    return { ...base, ...eligibilityOf(insight) }
}

export function buildCatalog(
    pins: readonly PinView[],
    metadata: WidgetPinMetadata,
    project: WidgetCatalogProject,
    snapshotPinIds?: ReadonlySet<string>
): WidgetCatalogBody {
    return {
        version: 1,
        host: project.host,
        projectId: project.projectId,
        projectName: project.projectName,
        pins: pins
            .slice(0, CATALOG_PIN_LIMIT)
            .map((pin) => catalogPin(pin, metadata, snapshotPinIds?.has(pin.shortcutId) ?? true)),
    }
}

/** The JSON the native module stores: the body with `writtenAt` before `pins`, as the contract lists the fields. */
export function catalogJson(body: WidgetCatalogBody, writtenAt: number): string {
    const { pins, ...head } = body
    return JSON.stringify({ ...head, writtenAt, pins })
}

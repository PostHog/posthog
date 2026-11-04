import type { BudgetFamily } from '@/api/budget'
import type { ScopedFeature } from '@/api/scopeErrors'
import { track } from '@/lib/analytics'
import type { PinDisplayMode, ViewEntry, ViewKind } from '@/model/views'

import type { ItemErrorKind } from './viewsCache'

// Typed wrappers for the Views events, so every screen sends the same property names and values.

export type ViewsScreen = 'list' | 'dashboard' | 'insight' | 'web_analytics'
export type RefreshTrigger = 'focus' | 'foreground' | 'pull' | 'range'
export type BlockedReason = 'bulk_floor' | 'dashboard_floor' | 'item_window'
/** `undo` is the toast's Undo, which reverses the pin or unpin just before it. */
export type PinSource = 'header' | 'row_menu' | 'swipe' | 'search' | 'undo'
export type RangeMethod = 'chip' | 'more' | 'custom' | 'step' | 'reset'

export function trackViewsOpened(props: { pinnedCount: number; fromCache: boolean }): void {
    track('mobile_views_opened', { pinned_count: props.pinnedCount, from_cache: props.fromCache })
}

export function trackViewOpened(props: {
    viewType: ViewKind
    from: ViewEntry
    displayMode: PinDisplayMode | null
    dataAgeSeconds: number | null
}): void {
    track('mobile_view_opened', {
        view_type: props.viewType,
        from: props.from,
        display_mode: props.displayMode,
        data_age_s: props.dataAgeSeconds,
    })
}

export function trackViewOpenedInWeb(props: {
    viewType: ViewKind | 'recordings' | 'person'
    reason: 'web_only' | 'action'
}): void {
    track('mobile_view_opened_in_web', { view_type: props.viewType, reason: props.reason })
}

export function trackViewPinned(props: { viewType: ViewKind; from: PinSource }): void {
    track('mobile_view_pinned', { view_type: props.viewType, from: props.from })
}

export function trackViewUnpinned(props: { viewType: ViewKind; from: PinSource; rowsDeleted: number }): void {
    track('mobile_view_unpinned', { view_type: props.viewType, from: props.from, rows_deleted: props.rowsDeleted })
}

export function trackPinsReordered(props: { pinCount: number; method: 'drag' | 'menu' }): void {
    track('mobile_pins_reordered', { pin_count: props.pinCount, method: props.method })
}

export function trackPinDisplayChanged(props: {
    viewType: ViewKind
    displayMode: PinDisplayMode
    previousMode: PinDisplayMode
}): void {
    track('mobile_pin_display_changed', {
        view_type: props.viewType,
        display_mode: props.displayMode,
        previous_mode: props.previousMode,
    })
}

export function trackPinTileChosen(props: { tileKind: string }): void {
    track('mobile_pin_tile_chosen', { tile_kind: props.tileKind })
}

export type PinHintDismissReason = 'close' | 'long_press'

export function trackPinHintShown(props: { kind: ViewKind; mode: PinDisplayMode }): void {
    track('mobile_pin_hint_shown', { kind: props.kind, mode: props.mode })
}

export function trackPinHintDismissed(props: { reason: PinHintDismissReason }): void {
    track('mobile_pin_hint_dismissed', { reason: props.reason })
}

export interface RefreshPassReport {
    trigger: RefreshTrigger
    screen: ViewsScreen
    itemsRequested: number
    itemsForced: number
    itemsComputed: number
    itemsFailed: number
    durationMs: number
    /** Age in seconds of the oldest good value on screen when the pass started. */
    maxAgeSeconds: number | null
    /** Seconds until a force is allowed, when the pull could not force anything. */
    blockedUntil: number | null
    blockedReason: BlockedReason | null
    cappedFamily: BudgetFamily | null
}

const CAPPED_EVENT_INTERVAL_MS = 60_000
const lastCappedEvent = new Map<BudgetFamily, number>()

/**
 * Sends `mobile_views_refreshed`. A pass that hit an empty budget sends at most one event per family per minute, so a
 * client bug that loops cannot flood analytics.
 */
export function trackViewsRefreshed(report: RefreshPassReport, now: number = Date.now()): void {
    if (report.cappedFamily) {
        const last = lastCappedEvent.get(report.cappedFamily)
        if (last !== undefined && now - last < CAPPED_EVENT_INTERVAL_MS) {
            return
        }
        lastCappedEvent.set(report.cappedFamily, now)
    }
    track('mobile_views_refreshed', {
        trigger: report.trigger,
        screen: report.screen,
        items_requested: report.itemsRequested,
        items_forced: report.itemsForced,
        items_computed: report.itemsComputed,
        items_failed: report.itemsFailed,
        duration_ms: Math.round(report.durationMs),
        max_age_s: report.maxAgeSeconds,
        blocked_until: report.blockedUntil,
        blocked_reason: report.blockedReason,
        capped: report.cappedFamily !== null,
        capped_family: report.cappedFamily,
    })
}

export type SearchSection = 'views' | 'dashboards' | 'insights'

export function trackViewsSearched(props: { section: SearchSection; queryLength: number; resultCount: number }): void {
    track('mobile_views_searched', {
        section: props.section,
        query_length: props.queryLength,
        result_count: props.resultCount,
    })
}

export function trackDateRangeChanged(props: {
    viewType: ViewKind
    method: RangeMethod
    range: string
    previousRange: string
}): void {
    track('mobile_date_range_changed', {
        view_type: props.viewType,
        method: props.method,
        range: props.range,
        previous_range: props.previousRange,
    })
}

export function trackDateRangeCompared(props: { viewType: ViewKind; enabled: boolean }): void {
    track('mobile_date_range_compared', { view_type: props.viewType, enabled: props.enabled })
}

export function trackChartPointSheetOpened(props: { entry: 'tooltip' | 'more' | 'accessibility' }): void {
    track('mobile_chart_point_sheet_opened', { entry: props.entry })
}

export function trackChartAboutOpened(props: { entry: 'icon' | 'point_sheet' | 'accessibility' }): void {
    track('mobile_chart_about_opened', { entry: props.entry })
}

export function trackChartRecordingsOpened(props: { resultCount: number }): void {
    track('mobile_chart_recordings_opened', { result_count: props.resultCount })
}

export function trackChartPeopleOpened(props: { resultCount: number }): void {
    track('mobile_chart_people_opened', { result_count: props.resultCount })
}

export type FullScreenEntry = 'button' | 'legend_more' | 'rows_more' | 'accessibility'

export function trackChartFullScreenOpened(props: { entry: FullScreenEntry; display: string }): void {
    track('mobile_chart_fullscreen_opened', { entry: props.entry, display: props.display })
}

export function trackViewsReauthShown(props: {
    missingScope: string | null
    state: 'reauth' | 'unavailable' | 'personal-key-missing-scopes'
    feature: ScopedFeature
}): void {
    track('mobile_views_reauth_shown', {
        missing_scope: props.missingScope,
        state: props.state,
        feature: props.feature,
    })
}

export type BrowseSection = 'dashboards' | 'insights'

export type BrowseListEntry = BrowseSection | 'errors' | 'replay'

export function trackBrowseListOpened(props: { section: BrowseListEntry; from: 'browse' | 'search' }): void {
    track('mobile_browse_list_opened', { section: props.section, from: props.from })
}

export function trackBrowseListPaged(props: { section: BrowseSection; pagesLoaded: number }): void {
    track('mobile_browse_list_paged', { section: props.section, pages_loaded: props.pagesLoaded })
}

export type EditPinsEntry = 'section' | 'menu'

export function trackEditPinsOpened(props: { from: EditPinsEntry; pinCount: number }): void {
    track('mobile_edit_pins_opened', { from: props.from, pin_count: props.pinCount })
}

export function trackEditPinsClosed(props: {
    reason: 'done' | 'no_pins'
    changes: number
    durationSeconds: number
}): void {
    track('mobile_edit_pins_closed', {
        reason: props.reason,
        changes: props.changes,
        duration_s: props.durationSeconds,
    })
}

export type TileSheetEntry = 'show_as' | 'menu' | 'removed_tile'

export function trackPinTileSheetOpened(props: { entry: TileSheetEntry; mode: 'number' | 'chart' }): void {
    track('mobile_pin_tile_sheet_opened', { entry: props.entry, mode: props.mode })
}

/** The tile counts are null when the sheet closed before the dashboard's tiles loaded. */
export function trackPinTileSheetClosed(props: {
    entry: TileSheetEntry
    picked: boolean
    tilesUsable: number | null
    tilesUnusable: number | null
}): void {
    track('mobile_pin_tile_sheet_closed', {
        entry: props.entry,
        picked: props.picked,
        tiles_usable: props.tilesUsable,
        tiles_unusable: props.tilesUnusable,
    })
}

export function trackViewsErrorShown(props: { screen: ViewsScreen | 'browse'; kind: ItemErrorKind }): void {
    track('mobile_views_error_shown', { screen: props.screen, kind: props.kind })
}

export type RangeSheetEntry = 'button' | 'not_saved' | 'accessibility'

export function trackDateRangeSheetOpened(props: { viewType: ViewKind; entry: RangeSheetEntry }): void {
    track('mobile_date_range_sheet_opened', { view_type: props.viewType, entry: props.entry })
}

export function trackViewMoreOpened(props: { viewType: ViewKind }): void {
    track('mobile_view_more_opened', { view_type: props.viewType })
}

export function trackDashboardTilesShown(props: { tilesTotal: number; tilesText: number; tilesWebOnly: number }): void {
    track('mobile_dashboard_tiles_shown', {
        tiles_total: props.tilesTotal,
        tiles_text: props.tilesText,
        tiles_web_only: props.tilesWebOnly,
    })
}

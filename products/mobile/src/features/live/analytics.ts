import type { NavChrome } from '@/features/tabs/navPinStore'
import { track } from '@/lib/analytics'
import type { LiveBreakdownKind, LiveEventKind, LiveProjectState } from '@/model/live'
import type { ViewEntry } from '@/model/views'

/** `load_failed`: the first read failed and the screen has nothing to show. `refresh_failed`: a later read failed. */
export type LiveErrorKind = 'load_failed' | 'refresh_failed'
export type LivePauseTrigger = 'button' | 'background'
export type LiveResumeTrigger = 'button' | 'foreground'
export type LiveEventAction = 'view_person' | 'watch_recording' | 'copy_distinct_id'
/** `card`: a tap on the map card. `map_country`: a tap on a country of the card's map, which opens it selected. */
export type LiveMapOpenedFrom = 'card' | 'map_country'
export type LiveCountrySource = 'map' | 'row'
/** Where a Meanwhile row on a Quiet or Not set up Live leads: a pinned view or the inbox. */
export type LiveMeanwhileTarget = 'view' | 'inbox'

export function trackLiveOpened(props: { from: ViewEntry; chrome: NavChrome }): void {
    track('mobile_live_opened', { from: props.from, chrome: props.chrome })
}

export function trackLiveOpenedInWeb(): void {
    track('mobile_live_opened_in_web')
}

export function trackLiveErrorShown(props: { kind: LiveErrorKind }): void {
    track('mobile_live_error_shown', { kind: props.kind })
}

export function trackLiveRefreshed(props: { trigger: 'pull' | 'resume' }): void {
    track('mobile_live_refreshed', { trigger: props.trigger })
}

export function trackLivePaused(props: { trigger: LivePauseTrigger }): void {
    track('mobile_live_paused', { trigger: props.trigger })
}

export function trackLiveResumed(props: { trigger: LiveResumeTrigger }): void {
    track('mobile_live_resumed', { trigger: props.trigger })
}

export function trackLiveBreakdownChanged(props: { breakdown: LiveBreakdownKind }): void {
    track('mobile_live_breakdown_changed', { breakdown: props.breakdown })
}

export function trackLiveEventSheetOpened(props: { kind: LiveEventKind }): void {
    track('mobile_live_event_sheet_opened', { kind: props.kind })
}

export function trackLiveEventActionTaken(props: { action: LiveEventAction }): void {
    track('mobile_live_event_action_taken', { action: props.action })
}

export function trackLiveMapOpened(props: { from: LiveMapOpenedFrom }): void {
    track('mobile_live_map_opened', { from: props.from })
}

export function trackLiveCountrySelected(props: { source: LiveCountrySource }): void {
    track('mobile_live_country_selected', { source: props.source })
}

export function trackLiveCountryCleared(): void {
    track('mobile_live_country_cleared')
}

export function trackLiveStateShown(props: { state: Exclude<LiveProjectState, 'web'> }): void {
    track('mobile_live_state_shown', { state: props.state })
}

export function trackLiveSetupOpened(): void {
    track('mobile_live_setup_opened')
}

export function trackLiveMeanwhileOpened(props: { target: LiveMeanwhileTarget }): void {
    track('mobile_live_meanwhile_opened', { target: props.target })
}

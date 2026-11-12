import type { NavChrome } from '@/features/tabs/navPinStore'
import { track } from '@/lib/analytics'
import type { LiveBreakdownKind, LiveEventKind } from '@/model/live'
import type { ViewEntry } from '@/model/views'

/** `load_failed`: the first read failed and the screen has nothing to show. `refresh_failed`: a later read failed. */
export type LiveErrorKind = 'load_failed' | 'refresh_failed'
export type LivePauseTrigger = 'button' | 'background'
export type LiveResumeTrigger = 'button' | 'foreground'
export type LiveEventAction = 'view_person' | 'watch_recording' | 'copy_distinct_id'

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

import posthog from 'lib/posthog-typed'

export type ScheduleOfferSurface = 'run_tab' | 'recordings_list'

export function captureScheduleOffer(
    step: 'shown' | 'accepted' | 'dismissed' | 'opened_scanner',
    surface: ScheduleOfferSurface,
    scannerId: string
): void {
    // pinned: analytics event names, renaming breaks the offer funnel
    posthog.capture(`replay_vision_schedule_offer_${step}`, { surface, scanner_id: scannerId })
}

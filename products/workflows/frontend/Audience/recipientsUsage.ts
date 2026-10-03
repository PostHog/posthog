import posthog from 'posthog-js'

// pinned: analytics event names and properties, renaming them breaks the Audience funnel; never send an address
interface RecipientsUsageEvents {
    'audience recipients filtered': { has_results: boolean }
    'audience recipients search cleared': Record<string, never>
    'audience recipients paged': { direction: 'next' | 'previous' }
    'audience recipients retried': Record<string, never>
    'audience unreachable persons opened': { count: number }
    'audience recipient opened': Record<string, never>
    'audience recipient retried': Record<string, never>
    'audience recipient address copied': Record<string, never>
}

export function captureRecipientsUsage<Event extends keyof RecipientsUsageEvents>(
    event: Event,
    properties: RecipientsUsageEvents[Event]
): void {
    posthog.capture(event, properties)
}

// PROTOTYPE (ticket #385), throwaway: one email-to-product journey, each click opens the session it started.
// Round 1: three structures for the send detail page on the existing /transactional/log/:id route, plus today's
// page for comparison, switchable via ?variant=. ?case= simulates the empty states. All data is invented.
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

export const PROTOTYPE_ENABLED = process.env.PROTOTYPE === '1'

export type JourneyVariant = 'today' | 'A' | 'B' | 'C'
export const JOURNEY_VARIANTS: { key: JourneyVariant; name: string }[] = [
    { key: 'today', name: 'no change, for comparison' },
    { key: 'A', name: 'Click timeline · low use: Watch · agent contract: activity' },
    { key: 'B', name: 'What they did after this email · low use: Watch, View person · agent contract: activity' },
    { key: 'C', name: 'The email, annotated · low use: Watch, delivery progress · agent contract: activity' },
]

/** A demo person in the preview's demo project, to open the Emails tab entry point. */
export const DEMO_PERSON_UUID = '01a1c547-38c8-002b-21e7-9d46b0e4c201'

export type JourneyCase =
    | 'full'
    | 'other-person'
    | 'no-person'
    | 'no-recording'
    | 'no-landing'
    | 'no-clicks'
    | 'not-tracked'
    | 'events-off'

export const JOURNEY_CASES: { key: JourneyCase; label: string }[] = [
    { key: 'full', label: 'Clicks with sessions' },
    { key: 'other-person', label: 'A click lands as someone else' },
    { key: 'no-person', label: 'Send named no distinct_id' },
    { key: 'no-recording', label: 'Session replay off' },
    { key: 'no-landing', label: 'Clicks, no landing found' },
    { key: 'no-clicks', label: 'Opened, no clicks yet' },
    { key: 'not-tracked', label: 'Clicks not tracked' },
    { key: 'events-off', label: 'Engagement events off' },
]

export interface JourneyPrototypeState {
    variant: JourneyVariant | null
    journeyCase: JourneyCase
    /** The link a variant focuses on, such as the selected link in C. */
    link: string | null
}

export function useEmailJourneyPrototype(): JourneyPrototypeState & {
    set: (changes: Partial<Record<'variant' | 'case' | 'link', string | null>>) => void
    withParams: (url: string) => string
} {
    const { searchParams, location, hashParams } = useValues(router)
    const { replace } = useActions(router)
    const variantParam = PROTOTYPE_ENABLED ? searchParams.variant : undefined
    const variant = JOURNEY_VARIANTS.some((v) => v.key === variantParam) ? (variantParam as JourneyVariant) : null
    const journeyCase = JOURNEY_CASES.some((c) => c.key === searchParams.case)
        ? (searchParams.case as JourneyCase)
        : 'full'

    return {
        variant,
        journeyCase,
        link: searchParams.link ?? null,
        set: (changes) => {
            const next: Record<string, any> = { ...searchParams }
            for (const [key, value] of Object.entries(changes)) {
                if (value === null) {
                    delete next[key]
                } else {
                    next[key] = value
                }
            }
            replace(location.pathname, next, hashParams)
        },
        withParams: (url) => {
            if (!variant) {
                return url
            }
            const params = new URLSearchParams({ variant })
            if (journeyCase !== 'full') {
                params.set('case', journeyCase)
            }
            return `${url}?${params.toString()}`
        },
    }
}

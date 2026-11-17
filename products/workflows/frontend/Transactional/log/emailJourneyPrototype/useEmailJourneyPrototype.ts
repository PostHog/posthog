// PROTOTYPE (ticket #385), throwaway: what one transactional email leads to in the product.
// Round 4: the transactional list shows each email's impact with highlights on top (variant L1), the email page keeps variant D (the
// impact funnel) with any event as the conversion, and the send detail page keeps variant A (the click timeline).
// Switch with ?variant=, simulate cases with ?case=, pick the conversion event with ?goal=. All data is invented.
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'

export const PROTOTYPE_ENABLED = process.env.PROTOTYPE === '1'

export type JourneySurface = 'list' | 'email' | 'send'
export type JourneyVariant = 'L1' | 'D' | 'today' | 'A'

const LIST_FLAGS = 'muscle memory: home to email page · known pain: transactional home · agent contract: emails list'

export const JOURNEY_VARIANTS: { key: JourneyVariant; surface: JourneySurface; name: string }[] = [
    { key: 'L1', surface: 'list', name: `Impact columns with highlights · ${LIST_FLAGS}` },
    {
        key: 'D',
        surface: 'email',
        name: 'Impact funnel · low use: email page · agent contract: email stats · muscle memory: default Metrics view · known pain: template page',
    },
    { key: 'today', surface: 'send', name: "today's send detail, for comparison" },
    { key: 'A', surface: 'send', name: 'Click timeline · low use: Watch · agent contract: activity' },
]

/** A demo person in the preview's demo project, to open the Emails tab entry point. */
export const DEMO_PERSON_UUID = '01a1c547-38c8-002b-21e7-9d46b0e4c201'

export type ListCase = 'full' | 'no-landing' | 'no-recording'
export type EmailCase = 'full' | 'no-scanner' | 'scanning' | 'no-goal' | 'no-landing' | 'no-recording' | 'not-tracked'
export type SendCase =
    | 'full'
    | 'other-person'
    | 'no-person'
    | 'no-recording'
    | 'no-landing'
    | 'no-clicks'
    | 'not-tracked'
    | 'events-off'
export type JourneyCase = ListCase | EmailCase | SendCase

export const JOURNEY_CASES: Record<JourneySurface, { key: JourneyCase; label: string }[]> = {
    list: [
        { key: 'full', label: 'Link tag and replay on' },
        { key: 'no-landing', label: 'Link tag not on yet' },
        { key: 'no-recording', label: 'Session replay off' },
    ],
    email: [
        { key: 'full', label: 'Scanner on, findings in' },
        { key: 'no-scanner', label: 'No scanner yet' },
        { key: 'scanning', label: 'Scanner just started' },
        { key: 'no-goal', label: 'No conversion event picked' },
        { key: 'no-landing', label: 'Link tag not on yet' },
        { key: 'no-recording', label: 'Session replay off' },
        { key: 'not-tracked', label: 'Clicks not tracked' },
    ],
    send: [
        { key: 'full', label: 'Clicks with sessions' },
        { key: 'other-person', label: 'A click lands as someone else' },
        { key: 'no-person', label: 'Send named no distinct_id' },
        { key: 'no-recording', label: 'Session replay off' },
        { key: 'no-landing', label: 'Clicks, no landing found' },
        { key: 'no-clicks', label: 'Opened, no clicks yet' },
        { key: 'not-tracked', label: 'Clicks not tracked' },
        { key: 'events-off', label: 'Engagement events off' },
    ],
}

/** The page each surface lives on. The scenes' own loaders ask for this ID and get a 404, which the prototype ignores. */
export function surfacePath(surface: JourneySurface): string {
    return surface === 'list'
        ? urls.transactional()
        : surface === 'email'
          ? urls.transactionalCodeEmail('prototype')
          : urls.transactionalEmailLogEntry('prototype')
}

export interface JourneyPrototypeState {
    variant: JourneyVariant | null
    surface: JourneySurface | null
    journeyCase: JourneyCase
    /** The link a variant focuses on. */
    link: string | null
    /** The event that counts as converted, picked on the email page. */
    goal: string | null
}

export function journeyUrl(variant: JourneyVariant, journeyCase?: JourneyCase | null, path?: string): string {
    const surface = JOURNEY_VARIANTS.find((v) => v.key === variant)!.surface
    const params = new URLSearchParams({ variant })
    if (journeyCase && journeyCase !== 'full') {
        params.set('case', journeyCase)
    }
    return `${path ?? surfacePath(surface)}?${params.toString()}`
}

export function useEmailJourneyPrototype(): JourneyPrototypeState & {
    set: (changes: Partial<Record<'variant' | 'case' | 'link' | 'goal', string | null>>) => void
    withParams: (url: string) => string
} {
    const { searchParams, location, hashParams } = useValues(router)
    const { replace } = useActions(router)
    const variantParam = PROTOTYPE_ENABLED ? searchParams.variant : undefined
    const found = JOURNEY_VARIANTS.find((v) => v.key === variantParam)
    const variant = found?.key ?? null
    const surface = found?.surface ?? null
    const journeyCase =
        surface && JOURNEY_CASES[surface].some((c) => c.key === searchParams.case)
            ? (searchParams.case as JourneyCase)
            : 'full'

    return {
        variant,
        surface,
        journeyCase,
        link: searchParams.link ?? null,
        goal: typeof searchParams.goal === 'string' ? searchParams.goal : null,
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
        withParams: (url) => (variant ? journeyUrl(variant, journeyCase, url) : url),
    }
}

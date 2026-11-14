// PROTOTYPE (ticket #320), throwaway: where the app tells a team it can send email from code.
// Round 1: three variants on the existing /transactional route, switchable via ?variant=.
// All state lives in the URL, so a variant and its simulated state are shareable and reload-stable.
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

export const PROTOTYPE_ENABLED = process.env.PROTOTYPE === '1'

export type PrototypeVariant = 'today' | 'A' | 'B' | 'C'
export const PROTOTYPE_VARIANTS: { key: PrototypeVariant; name: string }[] = [
    { key: 'today', name: 'Today, for comparison' },
    { key: 'A', name: 'A page in the Transactional section' },
    { key: 'B', name: 'A code-first empty state' },
    { key: 'C', name: 'A step after domain verification' },
]

export type DomainState = 'none' | 'pending' | 'verified'
export type EmailsState = 'none' | 'some'
export type FirstSendState = 'waiting' | 'arrived'

export interface PrototypeState {
    variant: PrototypeVariant | null
    domain: DomainState
    emails: EmailsState
    firstSend: FirstSendState
    view: string | null
}

export const PROTOTYPE_PARAM_KEYS = ['variant', 'domain', 'emails', 'firstSend', 'view'] as const

export function useSendFromCodePrototype(): PrototypeState & {
    set: (changes: Partial<Record<(typeof PROTOTYPE_PARAM_KEYS)[number], string | null>>) => void
    withParams: (url: string, extra?: Record<string, string | null>) => string
} {
    const { searchParams, location } = useValues(router)
    const { replace } = useActions(router)
    const variantParam = PROTOTYPE_ENABLED ? searchParams.variant : undefined
    const variant = PROTOTYPE_VARIANTS.some((v) => v.key === variantParam) ? (variantParam as PrototypeVariant) : null

    const state: PrototypeState = {
        variant,
        domain: (searchParams.domain as DomainState) ?? 'verified',
        emails: (searchParams.emails as EmailsState) ?? 'none',
        firstSend: (searchParams.firstSend as FirstSendState) ?? 'waiting',
        view: searchParams.view ?? null,
    }

    const prototypeParams = (): Record<string, string> => {
        const kept: Record<string, string> = {}
        for (const key of PROTOTYPE_PARAM_KEYS) {
            if (searchParams[key] != null && key !== 'view') {
                kept[key] = String(searchParams[key])
            }
        }
        return kept
    }

    return {
        ...state,
        set: (changes) => {
            const next: Record<string, any> = { ...searchParams }
            for (const [key, value] of Object.entries(changes)) {
                if (value === null) {
                    delete next[key]
                } else {
                    next[key] = value
                }
            }
            replace(location.pathname, next)
        },
        withParams: (url, extra = {}) => {
            if (!variant) {
                return url
            }
            const params = new URLSearchParams({ ...prototypeParams() })
            for (const [key, value] of Object.entries(extra)) {
                if (value === null) {
                    params.delete(key)
                } else {
                    params.set(key, value)
                }
            }
            return `${url}?${params.toString()}`
        },
    }
}

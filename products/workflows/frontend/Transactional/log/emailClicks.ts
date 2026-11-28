import type { TransactionalEmailLogEventApi } from 'products/messaging/frontend/generated/api.schemas'

export const MAX_SHOWN_CLICKS = 200

export interface EmailClick {
    at: string
    link: string | null
}

export interface EmailClickRow extends EmailClick {
    key: string
}

export type EmailClickLinks = 'loading' | 'failed' | 'loaded' | 'none'

function clicksOf(timeline: readonly TransactionalEmailLogEventApi[]): TransactionalEmailLogEventApi[] {
    return timeline.filter((event) => event.kind === 'clicked')
}

export function hasMoreClicks(timeline: readonly TransactionalEmailLogEventApi[]): boolean {
    return clicksOf(timeline).length > MAX_SHOWN_CLICKS
}

export function emailClickRows(
    timeline: readonly TransactionalEmailLogEventApi[],
    links: readonly EmailClick[]
): EmailClickRow[] {
    const linksAt = new Map<number, string[]>()
    for (const { at, link } of links) {
        if (link) {
            const instant = Date.parse(at)
            linksAt.set(instant, [...(linksAt.get(instant) ?? []), link])
        }
    }
    return clicksOf(timeline)
        .slice(-MAX_SHOWN_CLICKS)
        .map((event, index) => ({
            key: `${event.at}-${index}`,
            at: event.at,
            link: linksAt.get(Date.parse(event.at))?.shift() ?? null,
        }))
}

export function linkLabel(link: string): string {
    try {
        const url = new URL(link)
        const path = url.pathname === '/' && !url.search && !url.hash ? '' : url.pathname
        return `${url.host}${path}${url.search}${url.hash}`
    } catch {
        return link
    }
}

import { humanFriendlyDuration } from 'lib/utils/durations'
import { percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { WebPageDirectoryRow, WebPageDirectorySiteTotals } from '~/queries/schema/schema-general'

import { GoogleSearchConsoleSummary } from 'products/web_analytics/frontend/searchAndAi/searchAndAiQueries'

import { valueChange } from './pageReportsUtils'

const MIN_VISITORS_FOR_HEALTH = 30
const STRONG_SHARE_OF_SITE = 0.8
const WEAK_SHARE_OF_SITE = 0.5
const DECLINE_THRESHOLD = -0.2
const GOOD_SEARCH_POSITION = 10
const POOR_SEARCH_POSITION = 20
const MIN_AI_CRAWLERS = 3
const STRONG_BOUNCE_MARGIN = 0.05
const POOR_BOUNCE_MARGIN = 0.15
const MIN_ENGAGED_SECONDS = 30
const QUICK_EXIT_SECONDS = 10
const REDIRECT_SECONDS = 1

export type PageHealthKey = 'search' | 'ai' | 'engagement'

export type PageHealthStatus =
    | 'loading'
    | 'strong'
    | 'fair'
    | 'needs_attention'
    | 'not_found'
    | 'no_data'
    | 'not_set_up'

export interface PageHealthCard {
    key: PageHealthKey
    title: string
    status: PageHealthStatus
    headline: string
    reasons: string[]
}

export type GoogleSearchConsoleState = GoogleSearchConsoleSummary | 'not_connected' | 'loading' | 'error'

export interface PageHealthInput {
    page: WebPageDirectoryRow | null
    site: WebPageDirectorySiteTotals | null
    searchConsole: GoogleSearchConsoleState
}

export const PAGE_HEALTH_STATUS_LABEL: Record<PageHealthStatus, string> = {
    loading: 'Checking',
    strong: 'Strong',
    fair: 'Fair',
    needs_attention: 'Needs attention',
    not_found: 'Not found',
    no_data: 'Not enough data',
    not_set_up: 'Not set up',
}

const share = (part: number, whole: number): number => (whole > 0 ? part / whole : 0)

const formatPct = (value: number): string => percentage(value, value < 0.1 ? 1 : 0)

const atLeast = (value: number, threshold: number): boolean => value >= threshold - 1e-9

const atMost = (value: number, threshold: number): boolean => value <= threshold + 1e-9

const isDecline = (change: number | null): change is number => change !== null && atMost(change, DECLINE_THRESHOLD)

const loadingCard = (key: PageHealthKey, title: string): PageHealthCard => ({
    key,
    title,
    status: 'loading',
    headline: 'Checking this page',
    reasons: [],
})

const notEnoughVisitors = (key: PageHealthKey, title: string, visitors: number): PageHealthCard => ({
    key,
    title,
    status: 'no_data',
    headline: 'Not enough visitors yet',
    reasons: [
        `This page had ${pluralize(visitors, 'visitor')} in this period. Health needs at least ${MIN_VISITORS_FOR_HEALTH}.`,
    ],
})

export function computeSearchHealth({ page, site, searchConsole }: PageHealthInput): PageHealthCard {
    const title = 'Search visibility'
    if (!page || !site || searchConsole === 'loading') {
        return loadingCard('search', title)
    }
    const visitors = page.visitors?.current ?? 0
    if (visitors < MIN_VISITORS_FOR_HEALTH) {
        return notEnoughVisitors('search', title, visitors)
    }
    const google = page.googleSearch?.current ?? 0
    const pageShare = share(google, visitors)
    const siteShare = share(site.googleSearch?.current ?? 0, site.visitors?.current ?? 0)
    const googleChange = valueChange(page.googleSearch)
    const gsc = typeof searchConsole === 'string' ? null : searchConsole
    const connectHint =
        searchConsole === 'error'
            ? 'Google Search Console data did not load.'
            : 'Connect Google Search Console to see rankings and impressions.'

    if (google === 0 && (!gsc || gsc.impressions === 0)) {
        return {
            key: 'search',
            title,
            status: 'not_found',
            headline: 'No visitors from Google search',
            reasons: [
                gsc
                    ? 'Google Search Console shows no impressions for this page.'
                    : `None of this page's ${visitors.toLocaleString()} visitors arrived from Google search.`,
                ...(gsc ? [] : [connectHint]),
            ],
        }
    }

    const issues: string[] = []
    if (siteShare > 0 && !atLeast(pageShare, siteShare * WEAK_SHARE_OF_SITE)) {
        issues.push(`${formatPct(pageShare)} of visitors come from Google, against ${formatPct(siteShare)} site-wide.`)
    }
    if (isDecline(googleChange)) {
        issues.push(`Visitors from Google dropped ${formatPct(Math.abs(googleChange))} from the previous period.`)
    }
    if (gsc?.position != null && gsc.position > POOR_SEARCH_POSITION) {
        issues.push(`The average Google position is ${gsc.position.toFixed(1)}.`)
    }
    if (gsc && gsc.impressions > 0 && gsc.clicks === 0) {
        issues.push(`The page appeared in ${pluralize(gsc.impressions, 'search', 'searches')} but got no clicks.`)
    }

    const summary = `${formatPct(pageShare)} of visitors come from Google search, against ${formatPct(siteShare)} site-wide.`
    const positionLine = gsc?.position != null ? `The average Google position is ${gsc.position.toFixed(1)}.` : null
    if (issues.length > 0) {
        return { key: 'search', title, status: 'needs_attention', headline: issues[0], reasons: issues }
    }
    const isStrong =
        atLeast(pageShare, siteShare * STRONG_SHARE_OF_SITE) &&
        !isDecline(googleChange) &&
        (gsc?.position == null || gsc.position <= GOOD_SEARCH_POSITION)
    return {
        key: 'search',
        title,
        status: isStrong ? 'strong' : 'fair',
        headline: summary,
        reasons: [summary, ...(positionLine ? [positionLine] : []), ...(gsc ? [] : [connectHint])],
    }
}

export const areCrawlersMeasured = (site: WebPageDirectorySiteTotals): boolean =>
    site.serverLogs > 0 || (site.aiCrawls?.current ?? 0) > 0

export function computeAiHealth({ page, site }: PageHealthInput): PageHealthCard {
    const title = 'AI visibility'
    if (!page || !site) {
        return loadingCard('ai', title)
    }
    const visitors = page.visitors?.current ?? 0
    const referrals = page.aiReferrals?.current ?? 0
    const crawls = page.aiCrawls?.current ?? 0
    const crawlers = page.aiCrawlers ?? 0
    const crawlersMeasured = areCrawlersMeasured(site)
    const enoughVisitors = visitors >= MIN_VISITORS_FOR_HEALTH
    const pageShare = share(referrals, visitors)
    const siteShare = share(site.aiReferrals?.current ?? 0, site.visitors?.current ?? 0)
    const referralChange = valueChange(page.aiReferrals)
    const logsHint = 'Forward your server logs to see which AI crawlers read this page.'

    if (!crawlersMeasured && referrals === 0) {
        return {
            key: 'ai',
            title,
            status: 'not_set_up',
            headline: 'AI crawlers are not measured yet',
            reasons: [logsHint, 'No visitors arrived from an AI assistant in this period.'],
        }
    }
    if (crawls === 0 && !enoughVisitors) {
        return notEnoughVisitors('ai', title, visitors)
    }
    if (crawls === 0 && referrals === 0) {
        return {
            key: 'ai',
            title,
            status: 'not_found',
            headline: 'Not read or recommended by AI yet',
            reasons: ['No AI crawler read this page and no AI assistant sent visitors to it.'],
        }
    }

    const issues: string[] = []
    if (crawlersMeasured && crawls > 0 && referrals === 0) {
        issues.push(`Read by ${pluralize(crawlers, 'AI crawler')} but no AI assistant sent visitors.`)
    }
    if (crawlersMeasured && crawlers === 1) {
        issues.push('Only one AI crawler read this page.')
    }
    if (enoughVisitors && referrals > 0 && siteShare > 0 && !atLeast(pageShare, siteShare * WEAK_SHARE_OF_SITE)) {
        issues.push(
            `${formatPct(pageShare)} of visitors come from AI assistants, against ${formatPct(siteShare)} site-wide.`
        )
    }
    if (enoughVisitors && isDecline(referralChange)) {
        issues.push(
            `Visitors from AI assistants dropped ${formatPct(Math.abs(referralChange))} from the previous period.`
        )
    }

    const crawlerLine = crawlersMeasured
        ? `Read by ${pluralize(crawlers, 'AI crawler')} ${pluralize(crawls, 'time')}.`
        : logsHint
    const referralLine = `${pluralize(referrals, 'visitor')} arrived from an AI assistant.`
    const shareLine = `${formatPct(pageShare)} of visitors come from AI assistants, against ${formatPct(siteShare)} site-wide.`
    if (issues.length > 0) {
        return { key: 'ai', title, status: 'needs_attention', headline: issues[0], reasons: [...issues, crawlerLine] }
    }
    if (!enoughVisitors) {
        return notEnoughVisitors('ai', title, visitors)
    }
    const isStrong =
        referrals > 0 &&
        atLeast(pageShare, siteShare * STRONG_SHARE_OF_SITE) &&
        (!crawlersMeasured || crawlers >= MIN_AI_CRAWLERS)
    return {
        key: 'ai',
        title,
        status: isStrong ? 'strong' : 'fair',
        headline: referrals > 0 ? shareLine : referralLine,
        reasons: [shareLine, referralLine, crawlerLine],
    }
}

export function computeEngagementHealth({ page, site }: PageHealthInput): PageHealthCard {
    const title = 'Engagement'
    if (!page || !site) {
        return loadingCard('engagement', title)
    }
    const visitors = page.visitors?.current ?? 0
    if (visitors < MIN_VISITORS_FOR_HEALTH) {
        return notEnoughVisitors('engagement', title, visitors)
    }
    const p90 = page.timeOnPageP90 ?? null
    const bounce = page.bounceRate ?? null
    const siteP90 = site.timeOnPageP90 ?? null
    const siteBounce = site.bounceRate ?? null
    if (p90 === null && bounce === null) {
        return {
            key: 'engagement',
            title,
            status: 'no_data',
            headline: 'No timing data yet',
            reasons: ['Time on page needs a following pageview, so the last page of each visit is not counted.'],
        }
    }

    const issues: string[] = []
    if (p90 !== null && p90 < REDIRECT_SECONDS) {
        issues.push('Visits end in under a second, which usually means a redirect.')
    } else if (p90 !== null && p90 < QUICK_EXIT_SECONDS) {
        issues.push(`Most visitors leave within ${humanFriendlyDuration(p90)}.`)
    }
    if (bounce !== null && siteBounce !== null && atLeast(bounce, siteBounce + POOR_BOUNCE_MARGIN)) {
        issues.push(
            `${formatPct(bounce)} of visits that start here bounce, against ${formatPct(siteBounce)} site-wide.`
        )
    }

    const timeLine = p90 !== null ? `90% of visitors spend up to ${humanFriendlyDuration(p90)} on this page.` : null
    const bounceLine =
        bounce !== null
            ? `${formatPct(bounce)} of visits that start here bounce${siteBounce !== null ? `, against ${formatPct(siteBounce)} site-wide` : ''}.`
            : null
    const reasons = [timeLine, bounceLine].filter((line): line is string => !!line)
    if (issues.length > 0) {
        return { key: 'engagement', title, status: 'needs_attention', headline: issues[0], reasons: issues }
    }
    const isStrong =
        (bounce === null || siteBounce === null || atMost(bounce, siteBounce + STRONG_BOUNCE_MARGIN)) &&
        (p90 === null || atLeast(p90, Math.max(MIN_ENGAGED_SECONDS, (siteP90 ?? 0) * STRONG_SHARE_OF_SITE)))
    return {
        key: 'engagement',
        title,
        status: isStrong ? 'strong' : 'fair',
        headline: reasons[0],
        reasons,
    }
}

export interface PageHealthSummary extends PageHealthCard {
    value: string | null
    detail: string | null
}

const formatDuration = (seconds: number): string => (seconds < 1 ? 'Under 1s' : humanFriendlyDuration(seconds))

function summarizePageHealth(card: PageHealthCard, { page, site }: PageHealthInput): PageHealthSummary {
    if (!page || !site || card.status === 'loading') {
        return { ...card, value: null, detail: null }
    }
    const visitors = page.visitors?.current ?? 0
    const siteVisitors = site.visitors?.current ?? 0
    if (card.key === 'search') {
        return {
            ...card,
            value: visitors > 0 ? formatPct(share(page.googleSearch?.current ?? 0, visitors)) : null,
            detail: `from Google, site average ${formatPct(share(site.googleSearch?.current ?? 0, siteVisitors))}`,
        }
    }
    if (card.key === 'ai') {
        return {
            ...card,
            value: visitors > 0 ? formatPct(share(page.aiReferrals?.current ?? 0, visitors)) : null,
            detail: `from AI assistants, site average ${formatPct(share(site.aiReferrals?.current ?? 0, siteVisitors))}`,
        }
    }
    const p90 = page.timeOnPageP90 ?? null
    const bounce = page.bounceRate ?? null
    return {
        ...card,
        value: p90 !== null ? formatDuration(p90) : null,
        detail:
            [p90 !== null ? 'for 90% of visits' : null, bounce !== null ? `${formatPct(bounce)} bounce` : null]
                .filter(Boolean)
                .join(' · ') || null,
    }
}

export function computePageHealth(input: PageHealthInput): PageHealthSummary[] {
    return [computeSearchHealth(input), computeAiHealth(input), computeEngagementHealth(input)].map((card) =>
        summarizePageHealth(card, input)
    )
}

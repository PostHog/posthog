import { fromMarkdown } from 'mdast-util-from-markdown'

import { isObject } from 'lib/utils/guards'
import { urls } from 'scenes/urls'

import type { InsightShortId } from '~/types'

import type { SignalNodeApi } from 'products/signals/frontend/generated/api.schemas'

import { conversationsTicketUrl, genericSignalLink, signalEntityUrl } from './signalLinks'

function evidenceKey(signal: SignalNodeApi): string {
    const alertId =
        signal.source_product === 'analytics' && signal.extra && 'alert_id' in signal.extra
            ? signal.extra.alert_id
            : null
    return JSON.stringify([signal.source_product, alertId || signal.source_id || signal.signal_id])
}

export function selectReportEvidence(signals: SignalNodeApi[], limit: number = 3): SignalNodeApi[] {
    const newest = [...signals].sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
    const seen = new Set<string>()
    const unique = newest.filter((signal) => {
        const key = evidenceKey(signal)
        if (seen.has(key)) {
            return false
        }
        seen.add(key)
        return true
    })
    const products = new Set<string>()
    const diverse = unique.filter((signal) => {
        if (products.has(signal.source_product)) {
            return false
        }
        products.add(signal.source_product)
        return true
    })
    return [...diverse, ...unique.filter((signal) => !diverse.includes(signal))].slice(0, limit)
}

function evidenceUrl(href: string, projectUrl: string, entityLink: boolean = false): string | null {
    try {
        const project = new URL(projectUrl)
        const url = new URL(href, project.origin)
        if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) {
            return null
        }
        if (href.startsWith('/') && !href.startsWith('//') && !url.pathname.startsWith('/project/')) {
            url.pathname = `${project.pathname.replace(/\/$/, '')}${url.pathname}`
        }
        url.hash = ''
        if (entityLink) {
            url.search = ''
        }
        return url.href.replace(/\/$/, '')
    } catch {
        return null
    }
}

function signalSpecificUrls(signal: SignalNodeApi): { urls: string[]; ignoreSearch: boolean } | null {
    const extra: Record<string, unknown> = isObject(signal.extra) ? signal.extra : {}
    const alertId = typeof extra.alert_id === 'string' ? extra.alert_id : null
    if (signal.source_product === 'logs') {
        return { urls: alertId ? [urls.logsAlertDetail(alertId)] : [], ignoreSearch: false }
    }
    if (signal.source_product === 'analytics') {
        const notebookShortId = typeof extra.notebook_short_id === 'string' ? extra.notebook_short_id : null
        const insightShortId = typeof extra.insight_short_id === 'string' ? extra.insight_short_id : null
        return {
            urls: [
                alertId ? urls.alert(alertId) : null,
                notebookShortId ? urls.notebook(notebookShortId) : null,
                insightShortId ? urls.insightView(insightShortId as InsightShortId) : null,
            ].filter((url): url is string => url !== null),
            ignoreSearch: false,
        }
    }
    if (signal.source_product === 'replay_vision') {
        return {
            urls: typeof extra.session_id === 'string' ? [urls.replaySingle(extra.session_id)] : [],
            ignoreSearch: true,
        }
    }
    if (signal.source_product === 'llm_analytics' && signal.source_type === 'evaluation_report') {
        return {
            urls: typeof extra.evaluation_id === 'string' ? [urls.aiObservabilityEvaluation(extra.evaluation_id)] : [],
            ignoreSearch: true,
        }
    }
    return null
}

export function citedReportEvidence(markdown: string, signals: SignalNodeApi[], projectUrl: string): SignalNodeApi[] {
    const tree = fromMarkdown(markdown)
    const definitions = new Map(
        tree.children.flatMap((node) => (node.type === 'definition' ? [[node.identifier, node.url] as const] : []))
    )
    const links = new Set<string>()
    const entityLinks = new Set<string>()
    const visit = (node: ReturnType<typeof fromMarkdown>['children'][number]): void => {
        const href =
            node.type === 'link' ? node.url : node.type === 'linkReference' ? definitions.get(node.identifier) : null
        const url = href ? evidenceUrl(href, projectUrl) : null
        if (url) {
            links.add(url)
            entityLinks.add(evidenceUrl(href!, projectUrl, true)!)
        }
        if ('children' in node) {
            node.children.forEach(visit)
        }
    }
    tree.children.forEach(visit)
    const cited = signals.filter((signal) => {
        const specificUrls = signalSpecificUrls(signal)
        if (specificUrls !== null) {
            return specificUrls.urls.some((href) => {
                const url = evidenceUrl(href, projectUrl, specificUrls.ignoreSearch)
                return url !== null && (specificUrls.ignoreSearch ? entityLinks : links).has(url)
            })
        }
        const entityUrls = [signalEntityUrl(signal.source_product, signal.source_id)]
        if (signal.source_product === 'conversations') {
            entityUrls.push(conversationsTicketUrl(signal))
        }
        if (entityUrls.some((href) => href && entityLinks.has(evidenceUrl(href, projectUrl, true)!))) {
            return true
        }
        const source = genericSignalLink(signal)
        const url = source ? evidenceUrl(source.to, projectUrl) : null
        return url !== null && links.has(url)
    })
    return selectReportEvidence(cited, cited.length)
}

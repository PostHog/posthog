import { urls } from 'scenes/urls'

import { Node, SavedInsightNode } from '~/queries/schema/schema-general'
import { isDataVisualizationNode, isHogQLQuery, isSavedInsightNode } from '~/queries/utils'
import { InsightShortId } from '~/types'

export interface ChartOpenTarget {
    url: string
    label: string
}

// nginx accepts an 8 KiB request line by default, and that is the first thing in front of the app to
// refuse an over-long one. Sized against that rather than the browser's own much higher ceiling.
const MAX_OPEN_URL_LENGTH = 8000

// What an embedding surface sets to strip an insight down to its graph. A new insight wants the
// scene's own defaults for all of them, so they never travel in the URL.
const EMBED_PRESENTATION_KEYS = [
    'full',
    'embedded',
    'showFilters',
    'showHeader',
    'showTable',
    'showCorrelationTable',
    'showResults',
] as const

function withoutEmbedFlags(query: Node): Node {
    const node = { ...query } as unknown as Record<string, unknown>
    for (const key of EMBED_PRESENTATION_KEYS) {
        delete node[key]
    }
    return node as unknown as Node
}

/**
 * Where a report chart's open control points, and what to call it. `null` when there is nowhere to
 * send the reader, which is the caller's cue to drop the control rather than offer a dead link.
 *
 * The URL and the label are resolved together because `urls.insightNew` redirects a HogQL-backed
 * node to the SQL editor, so a single fixed label would describe the wrong destination for the SQL
 * charts a scout can attach.
 *
 * Pass the authored query, never the node `asEmbeddedChart` derives from it. Either way the
 * presentation flags are dropped before the query becomes a URL: the insight scene honors them, so
 * one that survived would land the reader on an insight with no filter bar, or no result body, and
 * nothing to iterate with. The derived node always carries them, and an authored one can too, since
 * a scout can copy a query from a surface that embeds it.
 */
export function chartOpenTarget(query: Node): ChartOpenTarget | null {
    // A `SavedInsightNode` holds a short id and no query of its own, so seeding a new insight from it
    // would open an empty editor. It resolves to the insight it already points at.
    if (isSavedInsightNode(query)) {
        // The query is stored unparsed and `isSavedInsightNode` reads only `kind`, so the short id
        // can be missing or not a string at all. Without this the control offers `/insights/undefined`
        // or a coerced `/insights/123` on the one chart whose body is already telling the reader the
        // insight can't be loaded. Same bar the renderer mounts on, so the two agree.
        const { shortId } = query as SavedInsightNode
        if (typeof shortId !== 'string' || !shortId) {
            return null
        }
        // Encoded as a path segment: `urls.insightView` interpolates straight into `/insights/${id}`,
        // and every other caller hands it a short id the API produced. This one is caller-authored, so
        // a value like `../../settings` would resolve to an unrelated scene — a link the reader has no
        // reason to distrust, on a chart whose body already says the insight is missing.
        return { url: urls.insightView(encodeURIComponent(shortId) as InsightShortId), label: 'Open insight' }
    }
    // Both forms carry the whole node in the query string, and the control opens a new tab, so the
    // URL goes out as a real request line. A chart near the 20,000-character query bound encodes to
    // several times that, past what a proxy in front of the app will accept, and the reader gets a
    // 414 from a chart that drew fine. Nothing here can shorten it, so the control is dropped.
    const url = urls.insightNew({ query: withoutEmbedFlags(query) })
    if (url.length > MAX_OPEN_URL_LENGTH) {
        return null
    }
    if (isDataVisualizationNode(query) && isHogQLQuery(query.source)) {
        return { url, label: 'Open in SQL editor' }
    }
    return { url, label: 'Open as new insight' }
}

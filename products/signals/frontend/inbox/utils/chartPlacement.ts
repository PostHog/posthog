// Where a report's charts go: which `chart:` references in the summary draw a chart at that point in
// the prose, and (by omission) which charts render after it instead.
//
// This parses the summary rather than pattern-matching it. A regex over the raw markdown disagrees
// with what the renderer actually does — it misses a link carrying a title (`[x](chart:a "note")`),
// matches inside a code span the renderer shows as literal text, and can't see that a reference sits
// in a table cell too narrow to hold a chart. Each disagreement costs a chart: one drawn twice,
// one drawn nowhere, one squashed to a sliver. So placement comes from a markdown parse (see
// `parseSummary` for where it still falls short of the renderer's), and the renderer resolves each
// reference by its position in the source.

import { fromMarkdown } from 'mdast-util-from-markdown'
import { gfmTableFromMarkdown } from 'mdast-util-gfm-table'
import { gfmTable } from 'micromark-extension-gfm-table'

import { CHART_REF_PREFIX } from 'lib/lemon-ui/LemonMarkdown'

// Matched against the id charset the backend enforces on `chart_id` (see `ChartArtefact`).
const CHART_REF_TARGET = new RegExp(`^${CHART_REF_PREFIX}([a-z0-9][a-z0-9_-]*)$`)

export interface ChartPlacements {
    /** Source offset of each reference that draws a chart there → the chart id it draws. */
    inlineByOffset: Map<number, string>
    /** Ids drawn somewhere in the prose. Every other chart renders after the summary. */
    inlineIds: Set<string>
}

/**
 * Only the table extension: it's the one GFM construct that changes where a chart reference lands.
 *
 * The renderer runs all of `remark-gfm`, so the two parses differ on the constructs left out here.
 * They agree on the answer anyway, because placement needs a reference to be the only thing in its
 * paragraph: `~~[x](chart:a)~~` reads below as a link between two `~~` text nodes and to the renderer
 * as a link under a `<del>`, and neither one is a reference alone in a paragraph. Reading the whole
 * dialect would mean pulling in `micromark-extension-gfm`, which buys nothing while that holds.
 */
function parseSummary(summary: string): { children?: unknown[] } | null {
    try {
        return fromMarkdown(summary, {
            extensions: [gfmTable()],
            mdastExtensions: [gfmTableFromMarkdown()],
        })
    } catch {
        // A summary this parser chokes on leaves every chart trailing the prose rather than none at all.
        return null
    }
}

/**
 * Resolve where each of a report's charts is drawn, from its summary's markdown.
 *
 * Only the first reference to an id places it — repeating a reference reads as pointing back at the
 * chart, not as asking for a second copy of it, and each extra copy would fire the query again.
 */
export function resolveChartPlacements(
    summary: string | null | undefined,
    chartIds: Iterable<string>
): ChartPlacements {
    const inlineByOffset = new Map<number, string>()
    const inlineIds = new Set<string>()
    const available = new Set(chartIds)
    if (typeof summary !== 'string' || !summary || available.size === 0) {
        return { inlineByOffset, inlineIds }
    }
    const tree = parseSummary(summary)
    if (!tree) {
        return { inlineByOffset, inlineIds }
    }

    // Only a reference sitting directly in a paragraph draws its chart there, because that is exactly
    // what the renderer can do with one: `LemonMarkdown` drops the `<p>` around a paragraph whose own
    // children are chart references, and a chart is block-level, so anywhere else it would land inside
    // an element that can't hold it — under the `<strong>`/`<em>` of a reference the author
    // formatted, in a heading's line of text, or in a table cell a few dozen pixels wide. Those still
    // read as their label, and their charts fall to the end of the report rather than being dropped.
    // A reference link (`[Daily][daily]` with `[daily]: chart:signups-drop` elsewhere) parses to a
    // `linkReference` holding an identifier instead of a destination, and its definition can sit
    // anywhere in the summary — so the definitions are collected before placement is decided. The
    // renderer resolves those references into ordinary anchors, so missing them here would leave the
    // label where the author put it and draw its chart after the prose instead.
    const definitions = new Map<string, string>()
    const collectDefinitions = (node: any): void => {
        // First definition wins, as it does in CommonMark when an identifier is defined twice.
        if (node?.type === 'definition' && typeof node.identifier === 'string' && !definitions.has(node.identifier)) {
            definitions.set(node.identifier, typeof node.url === 'string' ? node.url : '')
        }
        for (const child of node?.children ?? []) {
            collectDefinitions(child)
        }
    }
    collectDefinitions(tree)

    const destinationOf = (node: any): string => {
        if (node?.type === 'link') {
            return typeof node.url === 'string' ? node.url : ''
        }
        return (typeof node?.identifier === 'string' && definitions.get(node.identifier)) || ''
    }

    const isChartRef = (node: any): boolean =>
        (node?.type === 'link' || node?.type === 'linkReference') && CHART_REF_TARGET.test(destinationOf(node))
    // `break` is a CommonMark hard break, which the renderer draws as a `<br>` and counts as blank
    // for the same rule. Two references separated by one are still a chart-only paragraph.
    const isBlank = (node: any): boolean =>
        node?.type === 'break' || (node?.type === 'text' && typeof node.value === 'string' && node.value.trim() === '')

    // A reference also has to be all its paragraph holds. `LemonMarkdown` gives up the `<p>`
    // for those and nothing else, because a paragraph that also carries prose still needs it: the
    // words around the chart are a paragraph, and a block-level chart inside one is markup the
    // browser closes early and reparents. It also settles the constructs this parse doesn't read the
    // way the renderer does — `~~[Daily](chart:daily)~~` reaches here as a link between two `~~`
    // text nodes rather than under a `<del>`, and either way it isn't alone in its paragraph.
    const holdsOnlyChartRefs = (node: any): boolean => {
        const children: any[] = node?.children ?? []
        return children.some(isChartRef) && children.every((child) => isChartRef(child) || isBlank(child))
    }

    const visit = (node: any, inParagraph: boolean): void => {
        if (inParagraph && (node?.type === 'link' || node?.type === 'linkReference')) {
            const chartId = CHART_REF_TARGET.exec(destinationOf(node))?.[1]
            const offset = node.position?.start?.offset
            if (chartId && available.has(chartId) && !inlineIds.has(chartId) && typeof offset === 'number') {
                inlineByOffset.set(offset, chartId)
                inlineIds.add(chartId)
            }
        }
        for (const child of node?.children ?? []) {
            visit(child, node?.type === 'paragraph' && holdsOnlyChartRefs(node))
        }
    }
    visit(tree, false)

    return { inlineByOffset, inlineIds }
}

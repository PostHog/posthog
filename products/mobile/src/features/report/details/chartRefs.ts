import type { MarkdownIt } from 'react-native-markdown-display'

type Token = ReturnType<MarkdownIt['parse']>[number]

// Report summaries point at their charts with `[label](chart:chart_id)`. The web draws the chart there; the full
// report leaves charts to the report screen, so a reference reads as its label.
const CHART_HREF = /^chart:/i

function isChartLinkOpen(token: Token): boolean {
    return token.type === 'link_open' && CHART_HREF.test(token.attrGet('href') ?? '')
}

/** True when the inline content is chart references and whitespace only, which reads as an empty paragraph. */
function onlyChartRefs(children: readonly Token[]): boolean {
    let inChart = false
    let sawChart = false
    for (const child of children) {
        if (isChartLinkOpen(child)) {
            inChart = true
            sawChart = true
        } else if (inChart) {
            inChart = child.type !== 'link_close'
        } else if (!(child.type === 'softbreak' || (child.type === 'text' && !child.content.trim()))) {
            return false
        }
    }
    return sawChart
}

function withoutChartLinks(children: readonly Token[]): Token[] {
    const kept: Token[] = []
    let inChart = false
    for (const child of children) {
        if (isChartLinkOpen(child)) {
            inChart = true
        } else if (inChart && child.type === 'link_close') {
            inChart = false
        } else {
            kept.push(child)
        }
    }
    return kept
}

/**
 * Works on parsed tokens rather than the raw text, so it agrees with the renderer: a reference inside a code span
 * stays literal text, and a reference-style link to a `chart:` target counts too.
 */
export function chartRefsPlugin(md: MarkdownIt): void {
    md.core.ruler.after('inline', 'chart_refs', (state) => {
        const tokens: Token[] = []
        for (let index = 0; index < state.tokens.length; index++) {
            const token = state.tokens[index] as Token
            const inline = state.tokens[index + 1]
            if (token.type === 'paragraph_open' && inline?.children && onlyChartRefs(inline.children)) {
                index += 2
                continue
            }
            if (token.type === 'inline' && token.children) {
                token.children = withoutChartLinks(token.children)
            }
            tokens.push(token)
        }
        state.tokens = tokens
    })
}

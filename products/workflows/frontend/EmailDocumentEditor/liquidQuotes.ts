// Each stops at the next opening, so many unclosed tags take one pass.
const LIQUID_TAG = /\{\{(?:(?!\{\{|\{%)[\s\S])*?\}\}|\{%(?:(?!\{\{|\{%)[\s\S])*?%\}/y
const HTML_COMMENT_START = '<!--'
const HTML_COMMENT_END = '-->'

function liquidAt(html: string, position: number): string | null {
    LIQUID_TAG.lastIndex = position
    return LIQUID_TAG.exec(html)?.[0] ?? null
}

/** An HTML parser reads a `"` in Liquid as the end of a double-quoted attribute. A send decodes the entity. */
export function encodeLiquidQuotes(html: string): string {
    const out: string[] = []
    let inTag = false
    let quote: string | null = null
    let copied = 0
    let position = 0
    while (position < html.length) {
        const char = html[position]
        if (char === '{') {
            const liquid = liquidAt(html, position)
            if (liquid && quote === '"' && liquid.includes('"')) {
                out.push(html.slice(copied, position), liquid.replace(/"/g, '&quot;'))
                copied = position + liquid.length
            }
            position += liquid?.length ?? 1
            continue
        }
        if (quote) {
            quote = char === quote ? null : quote
        } else if (inTag) {
            if (char === '"' || char === "'") {
                quote = char
            } else if (char === '>') {
                inTag = false
            }
        } else if (html.startsWith(HTML_COMMENT_START, position)) {
            const end = html.indexOf(HTML_COMMENT_END, position)
            position = end < 0 ? html.length : end + HTML_COMMENT_END.length
            continue
        } else if (char === '<' && /[a-z]/i.test(html[position + 1] ?? '')) {
            inTag = true
        }
        position += 1
    }
    out.push(html.slice(copied))
    return out.join('')
}

import { marked } from 'marked'
import { memo, useMemo } from 'react'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

function parseMarkdownIntoBlocks(markdown: string): string[] {
    // Convert single newlines to markdown line breaks (two spaces + newline)
    const withLineBreaks = markdown.replace(/(?<!\n)\n(?!\n)/g, '  \n')
    const tokens = marked.lexer(withLineBreaks)
    return tokens.map((token) => token.raw)
}

/**
 * The optimized markdown renderer for messages.
 * Splits the markdown into blocks, so they can individually be memoized.
 *
 * `disableImages="all"`: the text comes from the model, which reads untrusted project data. An
 * auto-loading <img> would turn any image URL the model writes into a silent GET, which carries
 * conversation content in its path or query. `"all"` covers PostHog's own hosts too, because a
 * PostHog host accepts request data in a query string, so a same-host image URL is a sink as well.
 * Every image renders as a click-to-open link instead.
 */
export const MarkdownMessage = memo(function MarkdownMessage({
    content,
    id,
    className,
}: {
    content: string
    id: string
    className?: string
}): JSX.Element {
    const blocks = useMemo(() => parseMarkdownIntoBlocks(content), [content])
    return (
        <LemonMarkdown.Container className={className}>
            {blocks.map((block, index) => (
                <LemonMarkdown.Renderer key={`${id}-block_${index}`} disableImages="all">
                    {block}
                </LemonMarkdown.Renderer>
            ))}
        </LemonMarkdown.Container>
    )
})

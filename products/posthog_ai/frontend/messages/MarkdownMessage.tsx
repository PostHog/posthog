import { marked } from 'marked'
import { memo, useMemo } from 'react'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

function parseMarkdownIntoBlocks(markdown: string | undefined): string[] {
    if (!markdown) {
        return []
    }
    // Single-newline-to-line-break conversion is handled downstream by LemonMarkdown's remarkBreaks
    // plugin, which does it at the AST level without corrupting table rows.
    const tokens = marked.lexer(markdown)
    return tokens.map((token) => token.raw)
}

/**
 * The optimized markdown renderer for messages.
 * Splits the markdown into blocks, so they can individually be memoized.
 */
export const MarkdownMessage = memo(function MarkdownMessage({
    content,
    id,
    className,
}: {
    content: string | undefined
    id: string
    className?: string
}): JSX.Element {
    const blocks = useMemo(() => parseMarkdownIntoBlocks(content), [content])
    return (
        <LemonMarkdown.Container className={className}>
            {blocks.map((block, index) => (
                <LemonMarkdown.Renderer key={`${id}-block_${index}`}>{block}</LemonMarkdown.Renderer>
            ))}
        </LemonMarkdown.Container>
    )
})

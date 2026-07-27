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
                <LemonMarkdown.Renderer key={`${id}-block_${index}`}>{block}</LemonMarkdown.Renderer>
            ))}
        </LemonMarkdown.Container>
    )
})

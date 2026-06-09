import { marked } from 'marked'
import { memo, useId, useMemo } from 'react'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

/**
 * Split a markdown string into top-level block tokens.
 *
 * Streaming-friendly: each block is rendered (and memoized) independently, so a
 * partial trailing block — an unclosed code fence, a half-typed link — only
 * affects its own block instead of throwing off the whole document. This
 * mirrors the established Max AI thread renderer (see
 * `frontend/src/scenes/max/MarkdownMessage.tsx`).
 */
function parseMarkdownIntoBlocks(markdown: string): string[] {
    // Convert single newlines to markdown line breaks (two spaces + newline)
    const withLineBreaks = markdown.replace(/(?<!\n)\n(?!\n)/g, '  \n')
    const tokens = marked.lexer(withLineBreaks)
    return tokens.map((token) => token.raw)
}

interface MarkdownMessageProps {
    content: string
    className?: string
}

/**
 * Markdown renderer for agent/user message text, wrapping `LemonMarkdown`.
 *
 * Splits the content into blocks so they can individually be memoized, which
 * keeps re-renders cheap and tolerant of partial markdown while a message is
 * still streaming in.
 */
export const MarkdownMessage = memo(function MarkdownMessage({ content, className }: MarkdownMessageProps): JSX.Element {
    const id = useId()
    const blocks = useMemo(() => parseMarkdownIntoBlocks(content), [content])
    return (
        <LemonMarkdown.Container className={className}>
            {blocks.map((block, index) => (
                <LemonMarkdown.Renderer key={`${id}-block_${index}`}>{block}</LemonMarkdown.Renderer>
            ))}
        </LemonMarkdown.Container>
    )
})

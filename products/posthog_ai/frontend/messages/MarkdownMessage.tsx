import { marked } from 'marked'
import { memo, useMemo } from 'react'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet/CodeSnippet'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

function parseMarkdownIntoBlocks(markdown: string): string[] {
    // Convert single newlines to markdown line breaks (two spaces + newline)
    const withLineBreaks = markdown.replace(/(?<!\n)\n(?!\n)/g, '  \n')
    const tokens = marked.lexer(withLineBreaks)
    return tokens.map((token) => token.raw)
}

// Above this, content is shown collapsed in a scrollable code block rather than parsed as markdown —
// otherwise an oversized message or tool result (e.g. a raw HTML/CSS document) renders in full and
// buries the rest of the thread.
const OVERSIZED_CONTENT_LENGTH = 20_000
const OVERSIZED_CONTENT_VISIBLE_LINES = 40

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
    const isOversized = content.length > OVERSIZED_CONTENT_LENGTH
    const blocks = useMemo(() => (isOversized ? [] : parseMarkdownIntoBlocks(content)), [content, isOversized])

    if (isOversized) {
        return (
            <LemonMarkdown.Container className={className}>
                <CodeSnippet language={Language.Text} wrap maxLinesWithoutExpansion={OVERSIZED_CONTENT_VISIBLE_LINES}>
                    {content}
                </CodeSnippet>
            </LemonMarkdown.Container>
        )
    }

    return (
        <LemonMarkdown.Container className={className}>
            {blocks.map((block, index) => (
                <LemonMarkdown.Renderer key={`${id}-block_${index}`}>{block}</LemonMarkdown.Renderer>
            ))}
        </LemonMarkdown.Container>
    )
})

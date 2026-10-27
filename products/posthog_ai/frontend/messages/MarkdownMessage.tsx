import { marked } from 'marked'
import { memo, useMemo } from 'react'

import { rewriteAgentObjectTags } from 'lib/components/AgentObjectTags/rewriteAgentObjectTags'
import { LemonMarkdown, type LemonMarkdownComponents, type LemonMarkdownProps } from 'lib/lemon-ui/LemonMarkdown'
import { getCurrentTeamIdOrNone } from 'lib/utils/getAppContext'
import { urls } from 'scenes/urls'

function parseMarkdownIntoBlocks(markdown: string): string[] {
    // Convert single newlines to markdown line breaks (two spaces + newline)
    const withLineBreaks = markdown.replace(/(?<!\n)\n(?!\n)/g, '  \n')
    const tokens = marked.lexer(withLineBreaks)
    return tokens.map((token) => token.raw)
}

function rewriteObjectTags(markdown: string, teamId: number | null): string {
    // Agent object tags (`<insight id="…">label</insight>`) become links into the
    // current project, carrying the agent's label; stripping them instead posted
    // empty bullets wherever a reply cited an object.
    return rewriteAgentObjectTags(markdown, teamId !== null ? urls.project(teamId) : '')
}

/**
 * The optimized markdown renderer for messages.
 * Splits the markdown into blocks, so they can individually be memoized.
 */
export const MarkdownMessage = memo(function MarkdownMessage({
    content,
    id,
    className,
    components,
    renderCodeBlock,
}: {
    content: string
    id: string
    className?: string
    /** Element renderers that replace LemonMarkdown's own. Pass a stable (module-level) object. */
    components?: LemonMarkdownComponents
    /** Renderer for fenced code blocks. Pass a stable (module-level) function. */
    renderCodeBlock?: LemonMarkdownProps['renderCodeBlock']
}): JSX.Element {
    // The team id is a memo dependency so a project switch re-points existing links.
    const teamId = getCurrentTeamIdOrNone()
    const blocks = useMemo(() => parseMarkdownIntoBlocks(rewriteObjectTags(content, teamId)), [content, teamId])
    return (
        <LemonMarkdown.Container className={className}>
            {blocks.map((block, index) => (
                <LemonMarkdown.Renderer
                    key={`${id}-block_${index}`}
                    components={components}
                    renderCodeBlock={renderCodeBlock}
                >
                    {block}
                </LemonMarkdown.Renderer>
            ))}
        </LemonMarkdown.Container>
    )
})

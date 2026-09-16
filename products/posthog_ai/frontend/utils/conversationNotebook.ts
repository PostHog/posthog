import { escapeInlineMarkdownText, escapeMarkdownBlockLines } from 'lib/components/MarkdownNotebook/markdown'
import { NotebookPropValue } from 'lib/components/MarkdownNotebook/types'
import { uuid } from 'lib/utils/dom'
import {
    buildMarkdownNotebookContent,
    getSqlV2PropsFromQueryProp,
    serializeMarkdownNotebookComponent,
} from 'scenes/notebooks/Notebook/markdownNotebookV2'

import { ArtifactSource } from '~/queries/schema/schema-assistant-messages'
import { NodeKind } from '~/queries/schema/schema-general'

import { extractQueryResult, extractVisualizationArtifact } from '../components/tool/widgets/extractors'
import type { ThreadItem, ToolInvocation } from '../types/streamTypes'
import { toolInvocationToMessage } from './toolCallMessage'
import { visualizationTypeToQuery } from './visualizationQuery'

export interface ConversationBlocks {
    /** Markdown blocks in thread order: questions, live query cells, and answers. */
    blocks: string[]
    messageCount: number
    queryCount: number
}

export interface ConversationNotebook {
    markdown: string
    /** ProseMirror doc holding one markdown notebook node, the shape the notebooks API stores. */
    content: unknown
}

const INSIGHT_TOOLS = new Set(['insight-create', 'insight-update', 'insight-get', 'insight-query'])

/** Mirrors the blocks the agent's notebook tools write: a SQLV2 cell for HogQL, a Query embed otherwise. */
function toolCallToNotebookBlock(invocation: ToolInvocation): string | null {
    const message = toolInvocationToMessage(invocation)
    if (!message || message.status !== 'completed' || !message.innerToolName) {
        return null
    }
    if (INSIGHT_TOOLS.has(message.innerToolName)) {
        const artifact = extractVisualizationArtifact(message)
        if (artifact?.envelope.source === ArtifactSource.Insight) {
            return serializeMarkdownNotebookComponent('Query', {
                nodeId: uuid(),
                query: { kind: NodeKind.SavedInsightNode, shortId: artifact.envelope.artifact_id },
            })
        }
    }
    const result = extractQueryResult(message)
    if (!result) {
        return null
    }
    const query = result.content.query as unknown as NotebookPropValue
    const sqlProps = getSqlV2PropsFromQueryProp({ query })
    if (sqlProps) {
        return serializeMarkdownNotebookComponent('SQLV2', { nodeId: uuid(), ...sqlProps, returnVariable: 'sql_df' })
    }
    const renderable = visualizationTypeToQuery(result.content)
    return renderable
        ? serializeMarkdownNotebookComponent('Query', {
              nodeId: uuid(),
              query: renderable as unknown as NotebookPropValue,
          })
        : null
}

/**
 * Conversation prose is markdown the author meant to render, so only lines that would parse as a
 * notebook component tag are neutralized; anything else an assistant wrote stays formatted.
 */
function escapeComponentTagLines(markdown: string): string {
    return markdown
        .split('\n')
        .map((line) => (/^\s*<(?:[A-Z]|!--)/.test(line) ? line.replace('<', '\\<') : line))
        .join('\n')
}

export function collectConversationBlocks(
    threadItems: ThreadItem[],
    toolInvocations: Map<string, ToolInvocation>
): ConversationBlocks {
    const blocks: string[] = []
    let messageCount = 0
    let queryCount = 0
    for (const item of threadItems) {
        if (item.type === 'human_message' && item.text?.trim()) {
            messageCount += 1
            // A question is plain text, so it is escaped in full; the answer is markdown by design.
            blocks.push(`**You asked:** ${escapeMarkdownBlockLines(escapeInlineMarkdownText(item.text.trim()))}`)
        } else if (item.type === 'assistant_message' && item.text?.trim()) {
            messageCount += 1
            blocks.push(escapeComponentTagLines(item.text.trim()))
        } else if (item.type === 'tool_invocation' && item.toolCallId) {
            const invocation = toolInvocations.get(item.toolCallId)
            const block = invocation ? toolCallToNotebookBlock(invocation) : null
            if (block) {
                queryCount += 1
                blocks.push(block)
            }
        }
    }
    return { blocks, messageCount, queryCount }
}

export function buildConversationNotebook({
    title,
    summary,
    blocks,
}: {
    title: string
    summary: string
    blocks: string[]
}): ConversationNotebook {
    const lead = summary.trim() ? [escapeComponentTagLines(summary.trim())] : []
    const markdown = [`# ${escapeInlineMarkdownText(title.trim())}`, ...lead, ...blocks].join('\n\n')
    return { markdown, content: buildMarkdownNotebookContent(markdown) }
}

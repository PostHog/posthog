import { NotebookComponentProps } from 'lib/components/MarkdownNotebook/types'
import { uuid } from 'lib/utils/dom'
import { buildMarkdownNotebookContent } from 'scenes/notebooks/Notebook/markdownNotebookV2'
import { serializeMarkdownNotebookComponent } from 'scenes/notebooks/Notebook/markdownNotebookV2'

import { ArtifactSource } from '~/queries/schema/schema-assistant-messages'
import { NodeKind } from '~/queries/schema/schema-general'
import { isHogQLQuery, isInsightQueryNode } from '~/queries/utils'

import { extractQueryResult, extractVisualizationArtifact } from '../components/tool/widgets/extractors'
import type { ThreadItem, ToolInvocation } from '../types/streamTypes'
import { toolInvocationToMessage } from './toolCallMessage'

export interface ConversationNotebookInput {
    title: string
    summary: string
    threadItems: ThreadItem[]
    toolInvocations: Map<string, ToolInvocation>
}

export interface ConversationNotebook {
    markdown: string
    /** ProseMirror doc holding one markdown notebook node, the shape the notebooks API stores. */
    content: unknown
    messageCount: number
    queryCount: number
}

const INSIGHT_TOOLS = new Set(['insight-create', 'insight-update', 'insight-get', 'insight-query'])

/**
 * Turns a completed tool call into the notebook block the agent's own notebook tools would write:
 * a SQL cell for HogQL, a saved-insight embed for a saved insight, and a Query component for an
 * ephemeral insight query. Anything else (recordings, docs, writes) contributes nothing.
 */
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
    const query = result.content.query as unknown as Record<string, unknown>
    const source = isHogQLQuery(query) ? query : (query.source as Record<string, unknown> | undefined)
    if (source && isHogQLQuery(source) && typeof source.query === 'string' && source.query.trim()) {
        return serializeMarkdownNotebookComponent('SQLV2', {
            nodeId: uuid(),
            code: source.query,
            returnVariable: 'sql_df',
        })
    }
    if (isInsightQueryNode(query)) {
        return serializeMarkdownNotebookComponent('Query', {
            nodeId: uuid(),
            query: { kind: NodeKind.InsightVizNode, source: query } as unknown as NotebookComponentProps['query'],
        })
    }
    if (query.kind === NodeKind.InsightVizNode || query.kind === NodeKind.DataTableNode) {
        return serializeMarkdownNotebookComponent('Query', {
            nodeId: uuid(),
            query: query as unknown as NotebookComponentProps['query'],
        })
    }
    return null
}

/**
 * Writes the conversation so far as one markdown notebook: the classifier's title and lead, then
 * each question, the queries the assistant ran as live cells, and the assistant's answers.
 */
export function buildConversationNotebook({
    title,
    summary,
    threadItems,
    toolInvocations,
}: ConversationNotebookInput): ConversationNotebook {
    const blocks: string[] = [`# ${title.trim()}`]
    if (summary.trim()) {
        blocks.push(summary.trim())
    }
    let messageCount = 0
    let queryCount = 0
    for (const item of threadItems) {
        if (item.type === 'human_message' && item.text?.trim()) {
            messageCount += 1
            blocks.push(`**You asked:** ${item.text.trim()}`)
        } else if (item.type === 'assistant_message' && item.text?.trim()) {
            messageCount += 1
            blocks.push(item.text.trim())
        } else if (item.type === 'tool_invocation' && item.toolCallId) {
            const invocation = toolInvocations.get(item.toolCallId)
            const block = invocation ? toolCallToNotebookBlock(invocation) : null
            if (block) {
                queryCount += 1
                blocks.push(block)
            }
        }
    }
    const markdown = blocks.join('\n\n')
    return { markdown, content: buildMarkdownNotebookContent(markdown), messageCount, queryCount }
}

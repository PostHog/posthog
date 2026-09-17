import {
    escapeComponentTagLineStart,
    escapeInlineMarkdownText,
    escapeMarkdownBlockLines,
} from 'lib/components/MarkdownNotebook/markdown'
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
import type { IncidentOutline, ThreadItem, ToolInvocation } from '../types/streamTypes'
import { toolInvocationToMessage } from './toolCallMessage'
import { visualizationTypeToQuery } from './visualizationQuery'

/** A component cell before serialization; the node id is minted when the notebook is built. */
export interface ConversationComponentBlock {
    component: 'Query' | 'SQLV2'
    props: Record<string, NotebookPropValue>
}

export type ConversationBlock = string | ConversationComponentBlock

export interface ConversationBlocks {
    blocks: ConversationBlock[]
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
function toolCallToNotebookBlock(invocation: ToolInvocation): ConversationComponentBlock | null {
    const message = toolInvocationToMessage(invocation)
    if (!message || message.status !== 'completed' || !message.innerToolName) {
        return null
    }
    if (INSIGHT_TOOLS.has(message.innerToolName)) {
        const artifact = extractVisualizationArtifact(message)
        if (artifact?.envelope.source === ArtifactSource.Insight) {
            return {
                component: 'Query',
                props: { query: { kind: NodeKind.SavedInsightNode, shortId: artifact.envelope.artifact_id } },
            }
        }
    }
    const result = extractQueryResult(message)
    if (!result) {
        return null
    }
    const query = result.content.query as unknown as NotebookPropValue
    const sqlProps = getSqlV2PropsFromQueryProp({ query })
    if (sqlProps) {
        return { component: 'SQLV2', props: { ...sqlProps, returnVariable: 'sql_df' } }
    }
    const renderable = visualizationTypeToQuery(result.content)
    return renderable ? { component: 'Query', props: { query: renderable as unknown as NotebookPropValue } } : null
}

function escapeComponentTagLines(markdown: string): string {
    return markdown.split('\n').map(escapeComponentTagLineStart).join('\n')
}

/** Recomputed on every stream frame while the card is shown, so nothing here serializes or mints ids. */
export function collectConversationBlocks(
    threadItems: ThreadItem[],
    toolInvocations: Map<string, ToolInvocation>
): ConversationBlocks {
    const blocks: ConversationBlock[] = []
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

function serializeBlock(block: ConversationBlock): string {
    return typeof block === 'string'
        ? block
        : serializeMarkdownNotebookComponent(block.component, { nodeId: uuid(), ...block.props })
}

function section(heading: string, text: string): string[] {
    return text.trim() ? [`## ${heading}`, escapeComponentTagLines(text.trim())] : []
}

/** The incident write-up keeps the conversation as the evidence between the cause and the fix. */
function incidentSections(incident: IncidentOutline, blocks: string[]): string[] {
    return [
        ...section('Timeline', incident.timeline),
        ...section('Cause', incident.cause),
        '## Evidence',
        ...blocks,
        ...section('Fix', incident.fix),
    ]
}

export function buildConversationNotebook({
    title,
    summary,
    blocks,
    incident,
}: {
    title: string
    summary: string
    blocks: ConversationBlock[]
    incident?: IncidentOutline | null
}): ConversationNotebook {
    const lead = summary.trim() ? [escapeComponentTagLines(summary.trim())] : []
    const serialized = blocks.map(serializeBlock)
    const body = incident ? incidentSections(incident, serialized) : serialized
    const markdown = [`# ${escapeInlineMarkdownText(title.trim())}`, ...lead, ...body].join('\n\n')
    return { markdown, content: buildMarkdownNotebookContent(markdown) }
}

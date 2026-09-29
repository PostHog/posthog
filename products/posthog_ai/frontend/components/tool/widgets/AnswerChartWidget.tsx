import { useMemo } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import type { AgentChartBlock } from 'lib/components/AgentObjectTags/rewriteAgentObjectTags'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { ArtifactContentType, VisualizationArtifactContent } from '~/queries/schema/schema-assistant-messages'
import { NodeKind, SavedInsightNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { InsightShortId } from '~/types'

import { MessageTemplate } from '../../../messages/MessageTemplate'
import { VisualizationWidget, getQueryOpenTarget } from './VisualizationWidget'

const QUERY_CONTEXT_POSTHOG_AI: QueryContext = { limitContext: 'posthog_ai' } as const

export interface AnswerChartWidgetProps {
    block: AgentChartBlock
}

/** Renders a chart block from the agent's answer: a saved insight by short id, or a HogQL query. */
export function AnswerChartWidget({ block }: AnswerChartWidgetProps): JSX.Element {
    return block.kind === 'insight' ? (
        <SavedInsightChart shortId={block.shortId as InsightShortId} />
    ) : (
        <HogQLChart query={block.query} title={block.title} caption={block.caption} />
    )
}

function SavedInsightChart({ shortId }: { shortId: InsightShortId }): JSX.Element {
    const query = useMemo((): SavedInsightNode => ({ kind: NodeKind.SavedInsightNode, shortId }), [shortId])
    return (
        <MessageTemplate type="ai" className="w-full" wrapperClassName="w-full" boxClassName="flex flex-col w-full">
            <div className="flex flex-col h-96 overflow-auto">
                <Query query={query} readOnly embedded context={QUERY_CONTEXT_POSTHOG_AI} />
            </div>
            <div className="flex justify-end mt-2">
                <LemonButton
                    to={urls.insightView(shortId)}
                    targetBlank
                    icon={<IconOpenInNew />}
                    size="xsmall"
                    tooltip="Open insight"
                    data-attr="posthog-ai-answer-chart-open"
                />
            </div>
        </MessageTemplate>
    )
}

function HogQLChart({ query, title, caption }: { query: string; title?: string; caption?: string }): JSX.Element {
    const content = useMemo(
        (): VisualizationArtifactContent => ({
            content_type: ArtifactContentType.Visualization,
            query: { kind: NodeKind.HogQLQuery, query },
            name: title,
            description: caption,
        }),
        [query, title, caption]
    )
    const target = getQueryOpenTarget(content)
    return (
        <MessageTemplate
            type="ai"
            className="w-full"
            wrapperClassName="w-full"
            boxClassName="flex flex-col w-full gap-2"
        >
            {title && <h5 className="m-0">{title}</h5>}
            <VisualizationWidget content={content} openUrl={target.url} openTooltip={target.tooltip} embedded />
            {caption && <p className="m-0 text-secondary text-xs">{caption}</p>}
        </MessageTemplate>
    )
}

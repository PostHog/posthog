import { VisualizationBlock } from '~/queries/schema/schema-assistant-artifacts'
import {
    AnyAssistantGeneratedQuery,
    VisualizationArtifactContent,
    VisualizationItem,
} from '~/queries/schema/schema-assistant-messages'
import {
    DataVisualizationNode,
    InsightVizNode,
    NodeKind,
    QuerySchema,
    QuerySchemaRoot,
} from '~/queries/schema/schema-general'
import { isHogQLQuery, isInsightQueryNode } from '~/queries/utils'

export function castAssistantQuery(query: AnyAssistantGeneratedQuery | QuerySchemaRoot | null): QuerySchemaRoot | null {
    if (query) {
        return query as QuerySchemaRoot
    }
    return null
}

export const visualizationTypeToQuery = (
    visualization: VisualizationItem | VisualizationArtifactContent | VisualizationBlock
): QuerySchema | null => {
    if (!visualization) {
        return null
    }
    const source = castAssistantQuery('answer' in visualization ? visualization.answer : visualization.query)
    if (isHogQLQuery(source)) {
        return { kind: NodeKind.DataVisualizationNode, source: source } satisfies DataVisualizationNode
    }
    if (isInsightQueryNode(source)) {
        return { kind: NodeKind.InsightVizNode, source, showHeader: true } satisfies InsightVizNode
    }
    return source
}

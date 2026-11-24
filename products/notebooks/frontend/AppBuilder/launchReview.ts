import { NOTEBOOK_BLOCK_SEPARATOR } from 'lib/components/MarkdownNotebook/markdown'
import type { NotebookBlockNode, NotebookComponentProps } from 'lib/components/MarkdownNotebook/types'
import { uuid } from 'lib/utils/dom'
import { serializeMarkdownNotebookComponent, toNotebookPropValue } from 'scenes/notebooks/Notebook/markdownNotebookV2'

import { isEventsNode, isFunnelsQuery, isInsightVizNode } from '~/queries/schema/node-guards'
import { FunnelsQuery, NodeKind } from '~/queries/schema/schema-general'
import {
    FilterLogicalOperator,
    FunnelVizType,
    PropertyFilterType,
    PropertyOperator,
    RecordingUniversalFilters,
} from '~/types'

import type { NotebookAppLayoutApi } from '../generated/api.schemas'
import { appSourceCells, newAppBlock, pinAppCell } from './notebookAppLayout'

export interface LaunchReviewSources {
    flagId: number
    flagKey: string
    flagValue: string
    funnel: FunnelsQuery
}

export function notebookFunnel(cell: NotebookBlockNode): FunnelsQuery | null {
    if (cell.type !== 'component' || cell.tagName !== 'Query' || cell.props.id) {
        return null
    }
    const query = cell.props.query
    if (typeof query !== 'object' || !isInsightVizNode(query) || !isFunnelsQuery(query.source)) {
        return null
    }
    return hasEventSteps(query.source) ? query.source : null
}

function hasEventSteps(funnel: FunnelsQuery): boolean {
    const viz = funnel.funnelsFilter?.funnelVizType ?? FunnelVizType.Steps
    const steps = funnel.series
    return viz === FunnelVizType.Steps && Array.isArray(steps) && steps.length >= 2 && steps.every(isEventsNode)
}

export function buildLaunchReview(
    markdown: string,
    layout: NotebookAppLayoutApi,
    { flagId, flagKey, flagValue, funnel }: LaunchReviewSources
): { markdown: string; layout: NotebookAppLayoutApi; tabId: string } {
    const hasContent = layout.blocks.length > 0 || layout.tabs.length > 1
    if (layout.blocks.length > 97 || (hasContent && layout.tabs.length >= 20)) {
        throw new Error('Make room for a tab and three components before adding a launch review.')
    }
    const tabId = hasContent ? uuid() : layout.tabs[0].id
    const blocks = [...layout.blocks]
    const source = [markdown]
    function addCell(tag: string, title: string, props: NotebookComponentProps, existingId?: string): void {
        const id = existingId ?? uuid()
        if (!existingId) {
            source.push(serializeMarkdownNotebookComponent(tag, { ...props, nodeId: id, title }))
        }
        blocks.push(newAppBlock('cell', tabId, { node_id: id, title, display: 'output' }))
    }
    const existingFlag = appSourceCells(markdown).find(
        (cell) =>
            cell.type === 'component' && cell.tagName === 'FeatureFlag' && String(cell.props.id) === String(flagId)
    )
    const pinned = existingFlag ? pinAppCell(markdown, existingFlag.id) : { markdown, nodeId: undefined }
    source[0] = pinned.markdown
    addCell('FeatureFlag', 'Feature flag', { id: flagId }, pinned.nodeId)

    const flagProperty = {
        type: PropertyFilterType.Event as const,
        key: '$feature/' + flagKey,
        operator: PropertyOperator.Exact,
        value: [flagValue],
    }
    const scopedFunnel: FunnelsQuery = {
        ...funnel,
        response: undefined,
        series: funnel.series.map((step, i) =>
            i === 0 ? { ...step, properties: [...(step.properties ?? []), flagProperty] } : step
        ),
    }
    addCell('Query', 'Adoption funnel', {
        query: toNotebookPropValue({ kind: NodeKind.InsightVizNode, source: scopedFunnel }),
    })

    const recordingFilters: RecordingUniversalFilters = {
        date_from: funnel.dateRange?.date_from ?? '-30d',
        date_to: funnel.dateRange?.date_to,
        duration: [],
        filter_test_accounts: funnel.filterTestAccounts,
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [{ type: FilterLogicalOperator.And, values: [flagProperty] }],
        },
    }
    addCell('RecordingPlaylist', 'Recordings with this flag value', {
        universalFilters: toNotebookPropValue(recordingFilters),
    })
    return {
        markdown: source.filter(Boolean).join(NOTEBOOK_BLOCK_SEPARATOR),
        tabId,
        layout: {
            ...layout,
            title: layout.title || 'Feature launch review',
            tabs: hasContent ? [...layout.tabs, { id: tabId, title: 'Launch review' }] : layout.tabs,
            blocks,
        },
    }
}

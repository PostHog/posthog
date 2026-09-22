import type { SankeyChartLayout, SankeyLinkInput, SankeyNodeInput } from '@posthog/quill-charts'

import { FunnelPathsFilter, PathsFilter, PathsLink } from '~/queries/schema/schema-general'

import { FALLBACK_CANVAS_WIDTH } from './constants'
import { PathNodeData, PathTargetLink, isSelectedPathEndpoint, stripStepPrefix } from './pathUtils'
import { Paths } from './types'

export interface PathsGraphColors {
    node: string
    /** The start or end point the filter selected. */
    selectedNode: string
    link: string
}

export interface PathsGraph {
    nodes: SankeyNodeInput[]
    links: SankeyLinkInput<PathsLink>[]
}

/** Chart inputs for a paths result. Node ids are the result's `N_name` keys, which are unique per
 *  step, so the same page at two steps is two nodes. */
export function buildPathsGraph(
    paths: Paths,
    pathsFilter: PathsFilter,
    funnelPathsFilter: FunnelPathsFilter | undefined,
    colors: PathsGraphColors
): PathsGraph {
    const hasIncoming = new Set<string>()
    const hasOutgoing = new Set<string>()
    for (const link of paths.links) {
        hasOutgoing.add(link.source)
        hasIncoming.add(link.target)
    }
    const nodes = paths.nodes.map((node): SankeyNodeInput => {
        const selected = isSelectedPathEndpoint(pathsFilter, funnelPathsFilter, {
            name: stripStepPrefix(node.name),
            isPathStart: !hasIncoming.has(node.name),
            isPathEnd: !hasOutgoing.has(node.name),
        })
        return { id: node.name, color: selected ? colors.selectedNode : colors.node }
    })
    const links = paths.links.map(
        (link): SankeyLinkInput<PathsLink> => ({
            source: link.source,
            target: link.target,
            value: link.value,
            color: colors.link,
            meta: link,
        })
    )
    return { nodes, links }
}

/** The laid-out graph in the shape the card and hover logic works on. Node and link indices are
 *  the chart's, so a hover reported by the chart addresses the same node the logic holds. */
export function toPathNodeData(layout: SankeyChartLayout<unknown, PathsLink>): PathNodeData[] {
    const nodes = layout.nodes.map(
        (node): PathNodeData => ({
            name: node.id,
            targetLinks: [],
            sourceLinks: [],
            depth: node.column,
            layer: node.column,
            index: node.index,
            value: node.value,
            x0: node.x0,
            x1: node.x1,
            y0: node.y0,
            y1: node.y1,
            width: node.x1 - node.x0,
            height: node.y1 - node.y0,
        })
    )
    for (const link of layout.links) {
        const source = nodes[link.source.index]
        const target = nodes[link.target.index]
        const targetLink: PathTargetLink = {
            average_conversion_time: link.meta?.average_conversion_time ?? 0,
            index: link.index,
            source,
            target,
            value: link.value,
            width: link.width,
            y0: link.y0,
        }
        source.sourceLinks.push(targetLink)
        target.targetLinks.push(targetLink)
    }
    return nodes
}

export function maxPathLayer(paths: Paths): number {
    return paths.links.reduce((max, link) => Math.max(max, Number(link.target.match(/[^_]*/))), 0)
}

/** Chart width for a container. Past five steps the chart grows by a fifth of the container per
 *  step and the container scrolls, so long paths keep readable column spacing. A narrow container
 *  with three or more steps gets the fallback width for the same reason. */
export function pathsChartWidth(containerWidth: number, maxLayer: number): number {
    const minWidth = containerWidth > FALLBACK_CANVAS_WIDTH || maxLayer < 3 ? containerWidth : FALLBACK_CANVAS_WIDTH
    return maxLayer > 5 && containerWidth ? (minWidth / 5) * maxLayer : minWidth
}

import { RGBColor } from 'd3'

import { tryDecodeURIComponent } from 'lib/utils/url'

import { FunnelPathsFilter, PathsFilter } from '~/queries/schema/schema-general'
import { FunnelPathType } from '~/types'

import { PATH_NODE_CARD_HEIGHT, PATH_NODE_CARD_OVERLAP_GAP, PATH_NODE_CARD_TOP_OFFSET } from './constants'
// eslint-disable-next-line import/no-cycle
import { HIDE_PATH_CARD_HEIGHT } from './Paths'

const PATH_NODE_CARD_TOP_ADJUSTMENTS = 33

export interface PathTargetLink {
    average_conversion_time: number
    index: number
    source: PathNodeData
    target: PathNodeData
    value: number
    width: number
    y0: number
    color: RGBColor
}

export interface PathNodeData {
    name: string
    targetLinks: PathTargetLink[]
    sourceLinks: PathTargetLink[]
    depth: number
    width: number
    height: number
    index: number
    value: number
    x0: number
    x1: number
    y0: number
    y1: number
    layer: number
    source: PathNodeData
    target: PathNodeData
    visible?: boolean
    active?: boolean
    resolvedTop?: number
}

export function getForwardConnectedIndices(startNode: PathNodeData): {
    nodeIndices: Set<number>
    linkIndices: Set<number>
} {
    const nodeIndices = new Set<number>([startNode.index])
    const linkIndices = new Set<number>()

    const queue = [...startNode.sourceLinks]
    for (const link of queue) {
        if (!linkIndices.has(link.index)) {
            linkIndices.add(link.index)
            nodeIndices.add(link.target.index)
            for (const nextLink of link.target.sourceLinks) {
                queue.push(nextLink)
            }
        }
    }

    return { nodeIndices, linkIndices }
}

/** A node tall enough to show its card at all times, with no hover. */
export const isCardAlwaysVisible = (node: PathNodeData): boolean => node.y1 - node.y0 > HIDE_PATH_CARD_HEIGHT

export const activateNodes = (nodes: PathNodeData[], activeIndices: Set<number>): PathNodeData[] =>
    nodes.map((node) => ({
        ...node,
        visible: activeIndices.has(node.index) || isCardAlwaysVisible(node),
        active: activeIndices.has(node.index),
    }))

export const deactivateNodes = (nodes: PathNodeData[]): PathNodeData[] =>
    nodes.map((node) => ({
        ...node,
        visible: isCardAlwaysVisible(node),
        active: false,
    }))

/**
 * How far a card may move from its node to reach a free gap. A layer holds about 17 cards at the
 * minimum spacing, so a dense layer of short nodes runs out of gaps. Searching the whole canvas
 * then lands a card hundreds of pixels from the node it describes, which reads as belonging to a
 * different node. Past this distance the card keeps its own position instead.
 */
export const MAXIMUM_CARD_NUDGE = 2 * (PATH_NODE_CARD_HEIGHT + PATH_NODE_CARD_OVERLAP_GAP)

const findClosestAvailableCardTop = (
    naturalTop: number,
    occupiedTops: number[],
    canvasHeight: number
): { top: number; foundGap: boolean } => {
    const minimumDistance = PATH_NODE_CARD_HEIGHT + PATH_NODE_CARD_OVERLAP_GAP
    const maximumTop = Math.max(0, canvasHeight - PATH_NODE_CARD_HEIGHT)
    const clamp = (top: number): number => Math.min(Math.max(top, 0), maximumTop)
    const candidateTops = [
        clamp(naturalTop),
        ...occupiedTops.flatMap((occupiedTop) => [occupiedTop - minimumDistance, occupiedTop + minimumDistance]),
    ].filter((top) => top >= 0 && top <= maximumTop && Math.abs(top - naturalTop) <= MAXIMUM_CARD_NUDGE)

    const freeTop = candidateTops
        .filter((top) => occupiedTops.every((occupiedTop) => Math.abs(top - occupiedTop) >= minimumDistance))
        .sort((a, b) => Math.abs(a - naturalTop) - Math.abs(b - naturalTop) || a - b)[0]

    return freeTop === undefined ? { top: clamp(naturalTop), foundGap: false } : { top: freeTop, foundGap: true }
}

/**
 * Card positions per node index. Positions use every node, so hover changes do not move cards.
 */
export function resolveCardOverlaps(nodes: PathNodeData[], canvasHeight: number): Map<number, number> {
    const byLayer = new Map<number, PathNodeData[]>()
    const topByIndex = new Map<number, number>()
    for (const node of nodes) {
        topByIndex.set(node.index, calculatePathNodeCardTop(node, canvasHeight))
        const group = byLayer.get(node.layer) ?? []
        group.push(node)
        byLayer.set(node.layer, group)
    }

    const resolvedTops = new Map<number, number>()
    for (const group of byLayer.values()) {
        group.sort((a, b) => topByIndex.get(a.index)! - topByIndex.get(b.index)!)
        const alwaysVisibleNodes = group.filter(isCardAlwaysVisible)
        const occupiedTops: number[] = []
        let prevBottom = -Infinity
        for (const node of alwaysVisibleNodes) {
            const naturalTop = topByIndex.get(node.index)!
            const resolvedTop = Math.max(naturalTop, prevBottom + PATH_NODE_CARD_OVERLAP_GAP)
            resolvedTops.set(node.index, resolvedTop)
            occupiedTops.push(resolvedTop)
            prevBottom = resolvedTop + PATH_NODE_CARD_HEIGHT
        }

        occupiedTops.sort((a, b) => a - b)
        for (const node of group.filter((node) => !isCardAlwaysVisible(node))) {
            const { top, foundGap } = findClosestAvailableCardTop(
                topByIndex.get(node.index)!,
                occupiedTops,
                canvasHeight
            )
            resolvedTops.set(node.index, top)
            // A card that found no gap near its node keeps the position it wants and accepts the
            // overlap. It must not claim that position, because the cards after it would then be
            // pushed further from their own nodes to avoid a card that is already overlapping.
            if (foundGap) {
                occupiedTops.push(top)
                occupiedTops.sort((a, b) => a - b)
            }
        }
    }

    return resolvedTops
}

export function roundedRect(
    x: number,
    y: number,
    w: number,
    h: number,
    r: number,
    tl: boolean,
    tr: boolean,
    bl: boolean,
    br: boolean
): string {
    let retval
    retval = 'M' + (x + r) + ',' + y
    retval += 'h' + (w - 2 * r)
    if (tr) {
        retval += 'a' + r + ',' + r + ' 0 0 1 ' + r + ',' + r
    } else {
        retval += 'h' + r
        retval += 'v' + r
    }
    retval += 'v' + (h - 2 * r)
    if (br) {
        retval += 'a' + r + ',' + r + ' 0 0 1 ' + -r + ',' + r
    } else {
        retval += 'v' + r
        retval += 'h' + -r
    }
    retval += 'h' + (2 * r - w)
    if (bl) {
        retval += 'a' + r + ',' + r + ' 0 0 1 ' + -r + ',' + -r
    } else {
        retval += 'h' + -r
        retval += 'v' + -r
    }
    retval += 'v' + (2 * r - h)
    if (tl) {
        retval += 'a' + r + ',' + r + ' 0 0 1 ' + r + ',' + -r
    } else {
        retval += 'v' + -r
        retval += 'h' + r
    }
    retval += 'z'
    return retval
}

export function pageUrl(d: PathNodeData, display?: boolean, showFullUrls?: boolean): string {
    const incomingUrls = d.targetLinks
        .map((l) => l?.source?.name?.replace(/(^[0-9]+_)/, ''))
        .filter((a) => {
            try {
                new URL(a)
            } catch {
                return false
            }
            return a
        })
        .map((a) => new URL(a))
    const incomingDomains = Array.from(new Set(incomingUrls.map((url) => url.origin)))

    let name = d.name.replace(/(^[0-9]+_)/, '')

    if (!display) {
        return name
    }

    try {
        const url = new URL(name)
        name = incomingDomains.length !== 1 ? url.href.replace(/(^\w+:|^)\/\//, '') : url.pathname + url.search
        if (url.hash?.includes('/')) {
            name += url.hash
        }
        // Decode URL-encoded characters (e.g., %3C becomes <) to display path cleaning aliases correctly
        name = tryDecodeURIComponent(name)
    } catch {
        // discard if invalid url
    }

    if (showFullUrls) {
        return name
    }
    return name.length > 15
        ? name.substring(0, 6) + '...' + name.slice(-8)
        : name.length < 4 && d.name.length < 25
          ? d.name.replace(/(^[0-9]+_)/, '')
          : name
}

export const isSelectedPathStartOrEnd = (
    pathsFilter: PathsFilter,
    funnelPathsFilter: FunnelPathsFilter,
    pathItemCard: PathNodeData
): boolean => {
    const cardName = pageUrl(pathItemCard)
    const isPathStart = pathItemCard.targetLinks.length === 0
    const isPathEnd = pathItemCard.sourceLinks.length === 0
    const { startPoint, endPoint } = pathsFilter
    const { funnelPathType, funnelSource, funnelStep } = funnelPathsFilter || {}

    return (
        (startPoint === cardName && isPathStart) ||
        (endPoint === cardName && isPathEnd) ||
        (funnelPathType === FunnelPathType.between &&
            ((cardName === funnelSource?.series[funnelStep! - 1].name && isPathEnd) ||
                (cardName === funnelSource?.series[funnelStep! - 2].name && isPathStart)))
    )
}

export const calculatePathNodeCardTop = (node: PathNodeData, canvasHeight: number): number => {
    const isNodeCutoff = node.y1 - node.y0 < HIDE_PATH_CARD_HEIGHT && node.y1 > canvasHeight - HIDE_PATH_CARD_HEIGHT
    const isPathEnd = node.sourceLinks.length === 0
    const result = !isPathEnd ? node.y0 + PATH_NODE_CARD_TOP_OFFSET : node.y0 + (node.y1 - node.y0) / 2
    if (isNodeCutoff) {
        return result - PATH_NODE_CARD_TOP_ADJUSTMENTS
    }
    return result
}

import { getEmailStepHtml } from '../steps/emailStepHtml'
import type { HogFlowAction } from '../types'
import { NODE_HEIGHT, NODE_WIDTH } from './constants'

// Matches the `graphNode` size of EmailPreviewThumbnail, which renders inside the node border.
const EMAIL_THUMBNAIL_WIDTH = 180
const NODE_BORDER_WIDTH = 1
const EMAIL_NODE_WIDTH = EMAIL_THUMBNAIL_WIDTH + 2 * NODE_BORDER_WIDTH
const EMAIL_NODE_PREVIEW_HEIGHT = 200

export type NodeSize = { width: number; height: number }

export const DEFAULT_NODE_SIZE: NodeSize = { width: NODE_WIDTH, height: NODE_HEIGHT }

export function getNodeSize(action: HogFlowAction): NodeSize {
    if (getEmailStepHtml(action)) {
        return { width: EMAIL_NODE_WIDTH, height: NODE_HEIGHT + EMAIL_NODE_PREVIEW_HEIGHT }
    }
    return DEFAULT_NODE_SIZE
}

export function topHandlePosition({ width }: NodeSize): { x: number; y: number } {
    return { x: width / 2, y: 0 }
}

export function bottomHandlePosition({ width, height }: NodeSize): { x: number; y: number } {
    return { x: width / 2, y: height }
}

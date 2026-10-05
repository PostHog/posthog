import { hasEmailPreview } from '../steps/emailStepHtml'
import type { HogFlowAction } from '../types'
import { NODE_HEIGHT, NODE_WIDTH } from './constants'

const EMAIL_NODE_WIDTH = 180
const EMAIL_NODE_PREVIEW_HEIGHT = 200

export type NodeSize = { width: number; height: number }

export const DEFAULT_NODE_SIZE: NodeSize = { width: NODE_WIDTH, height: NODE_HEIGHT }

export function getNodeSize(action: HogFlowAction | undefined): NodeSize {
    if (action && hasEmailPreview(action)) {
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

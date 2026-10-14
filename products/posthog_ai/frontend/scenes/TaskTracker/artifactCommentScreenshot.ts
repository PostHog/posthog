import { captureElementImage } from 'lib/utils/captureElementImage'
import { uuid } from 'lib/utils/dom'

export const COMMENT_SURFACE_ATTR = 'data-artifact-comment-surface'
export const COMMENT_MARK_ATTR = 'data-artifact-comment-mark'
const PENDING_CARD_ATTR = 'data-pending-artifact-comment'

const PADDING_PX = 48
const MIN_SIZE_PX = 240
const MAX_SIZE_PX = 1200
const MAX_PIXEL_RATIO = 2
const MARK_COLOR = '#f54e00'

interface Box {
    left: number
    top: number
    right: number
    bottom: number
}

function loadImage(blob: Blob): Promise<HTMLImageElement> {
    return new Promise((resolve, reject) => {
        const url = URL.createObjectURL(blob)
        const image = new Image()
        image.onload = () => {
            URL.revokeObjectURL(url)
            resolve(image)
        }
        image.onerror = () => {
            URL.revokeObjectURL(url)
            reject(new Error('The screenshot did not load'))
        }
        image.src = url
    })
}

function grow(box: Box, width: number, height: number): Box {
    const centerX = (box.left + box.right) / 2
    const centerY = (box.top + box.bottom) / 2
    const halfWidth = Math.min(Math.max(box.right - box.left + PADDING_PX * 2, MIN_SIZE_PX), MAX_SIZE_PX) / 2
    const halfHeight = Math.min(Math.max(box.bottom - box.top + PADDING_PX * 2, MIN_SIZE_PX), MAX_SIZE_PX) / 2
    return {
        left: Math.max(0, centerX - halfWidth),
        top: Math.max(0, centerY - halfHeight),
        right: Math.min(width, centerX + halfWidth),
        bottom: Math.min(height, centerY + halfHeight),
    }
}

export async function captureCommentScreenshot(card: HTMLElement): Promise<File | null> {
    const surface = card.closest<HTMLElement>(`[${COMMENT_SURFACE_ATTR}]`)
    const marks = surface ? Array.from(surface.querySelectorAll<HTMLElement>(`[${COMMENT_MARK_ATTR}]`)) : []
    if (!surface || marks.length === 0) {
        return null
    }
    const origin = surface.getBoundingClientRect()
    const scaleX = origin.width / surface.offsetWidth || 1
    const scaleY = origin.height / surface.offsetHeight || 1
    const markBoxes: Box[] = marks.map((mark) => {
        const rect = mark.getBoundingClientRect()
        return {
            left: (rect.left - origin.left) / scaleX,
            top: (rect.top - origin.top) / scaleY,
            right: (rect.right - origin.left) / scaleX,
            bottom: (rect.bottom - origin.top) / scaleY,
        }
    })
    const marked: Box = {
        left: Math.min(...markBoxes.map((box) => box.left)),
        top: Math.min(...markBoxes.map((box) => box.top)),
        right: Math.max(...markBoxes.map((box) => box.right)),
        bottom: Math.max(...markBoxes.map((box) => box.bottom)),
    }
    const crop = grow(marked, surface.offsetWidth, surface.offsetHeight)
    const width = Math.round(crop.right - crop.left)
    const height = Math.round(crop.bottom - crop.top)
    try {
        const pixelRatio = Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO)
        const blob = await captureElementImage(surface, {
            width,
            height,
            pixelRatio,
            style: { transform: `translate(${-crop.left}px, ${-crop.top}px)`, transformOrigin: 'top left' },
            filter: (node) => !(node instanceof Element && node.hasAttribute(PENDING_CARD_ATTR)),
        })
        const image = await loadImage(blob)
        const ratio = image.width / width
        const canvas = document.createElement('canvas')
        canvas.width = image.width
        canvas.height = image.height
        const context = canvas.getContext('2d')
        if (!context) {
            return null
        }
        context.drawImage(image, 0, 0)
        context.strokeStyle = MARK_COLOR
        context.lineWidth = 2 * ratio
        for (const box of markBoxes) {
            context.strokeRect(
                (box.left - crop.left - 2) * ratio,
                (box.top - crop.top - 2) * ratio,
                (box.right - box.left + 4) * ratio,
                (box.bottom - box.top + 4) * ratio
            )
        }
        const png = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'))
        return png ? new File([png], `comment-${uuid().slice(0, 8)}.png`, { type: 'image/png' }) : null
    } catch {
        return null
    }
}

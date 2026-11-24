import { captureElementImage } from 'lib/utils/captureElementImage'
import { canCopyImageToClipboard } from 'lib/utils/copyImageToClipboard'

/** Elements with this class are on the share card for the viewer, not for the picture. */
export const SHARE_ACTIONS_CLASS = 'MCPWrapped__share-actions'

// A full-height phone story, whatever size the card renders at on screen.
const IMAGE_WIDTH = 1080
const IMAGE_HEIGHT = 1920
const IMAGE_TYPE = 'image/png'

export type ShareOutcome = 'done' | 'unsupported' | 'failed' | 'cancelled'

export function captureShareCard(element: HTMLElement): Promise<Blob> {
    return captureElementImage(element, {
        filter: (node) => !(node instanceof Element && node.classList.contains(SHARE_ACTIONS_CLASS)),
        // Square corners, so the picture fills the whole frame when it is posted.
        style: { transform: 'none', margin: '0', borderRadius: '0' },
        type: IMAGE_TYPE,
        canvasWidth: IMAGE_WIDTH,
        canvasHeight: IMAGE_HEIGHT,
        pixelRatio: 1,
    })
}

export async function copyShareCard(element: HTMLElement): Promise<ShareOutcome> {
    if (!canCopyImageToClipboard()) {
        return 'unsupported'
    }
    // Safari only accepts a clipboard write that starts in the same task as the click, so the capture is
    // handed to the ClipboardItem as a pending promise rather than awaited first.
    const capture = captureShareCard(element)
    capture.catch(() => {})
    try {
        await navigator.clipboard.write([new ClipboardItem({ [IMAGE_TYPE]: capture })])
        return 'done'
    } catch {
        return 'failed'
    }
}

export function canShareFiles(): boolean {
    return typeof navigator.share === 'function' && typeof navigator.canShare === 'function'
}

export async function shareShareCard(element: HTMLElement, fileName: string, text: string): Promise<ShareOutcome> {
    if (!canShareFiles()) {
        return 'unsupported'
    }
    try {
        const file = new File([await captureShareCard(element)], fileName, { type: IMAGE_TYPE })
        if (!navigator.canShare({ files: [file] })) {
            return 'unsupported'
        }
        await navigator.share({ files: [file], text })
        return 'done'
    } catch (error) {
        return error instanceof DOMException && error.name === 'AbortError' ? 'cancelled' : 'failed'
    }
}

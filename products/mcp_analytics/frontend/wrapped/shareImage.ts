import { captureElementImage } from 'lib/utils/captureElementImage'

// A full-height phone story, whatever size the card renders at on screen.
const IMAGE_WIDTH = 1080
const IMAGE_HEIGHT = 1920
const IMAGE_TYPE = 'image/png'

export function captureShareCard(element: HTMLElement): Promise<Blob> {
    return captureElementImage(element, {
        // Square corners, so the picture fills the whole frame when it is posted.
        style: { transform: 'none', margin: '0', borderRadius: '0' },
        type: IMAGE_TYPE,
        canvasWidth: IMAGE_WIDTH,
        canvasHeight: IMAGE_HEIGHT,
        pixelRatio: 1,
    })
}

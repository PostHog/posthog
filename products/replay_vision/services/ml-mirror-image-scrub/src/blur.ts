// Stage-1 scrub: downsample + gaussian blur, kept matching nodejs/.../anonymize/blur.ts so the mirror's
// baseline equals the inline anonymizer's. Pure sharp (libvips), no ML deps, to keep the consumer image
// lean; Stage 2 swaps this for advancedScrub in scrub.ts.
import sharp from 'sharp'

const DOWNSAMPLE_RATIO = 0.12
const BLUR_SIGMA = 2.34
const MAX_LONG_SIDE = 96
// Cap decoded input size so one absurd image can't balloon libvips memory (a compressed image can
// decode to many times its byte size). 50 MP is generous for real screenshots; larger inputs throw.
const LIMIT_INPUT_PIXELS = 50_000_000

/** Input that sharp can't decode (or has no readable dimensions): a permanent reject, never a transient
 *  failure — the caller maps this to a distinct HTTP status so the consumer drops it instead of replaying. */
export class UndecodableImageError extends Error {}

function targetDims(w: number, h: number): [number, number] {
    const scale = Math.min(DOWNSAMPLE_RATIO, MAX_LONG_SIDE / Math.max(w, h))
    return [Math.max(1, Math.round(w * scale)), Math.max(1, Math.round(h * scale))]
}

export async function blurOnly(input: Buffer): Promise<Buffer> {
    let width: number | undefined
    let height: number | undefined
    try {
        const meta = await sharp(input, { limitInputPixels: LIMIT_INPUT_PIXELS }).metadata()
        width = meta.width
        height = meta.height
    } catch (e) {
        throw new UndecodableImageError(String(e))
    }
    if (width === undefined || height === undefined) {
        // Don't silently blur a 1x1: a header with no dimensions is undecodable, not a real image.
        throw new UndecodableImageError('image has no readable dimensions')
    }
    const [tw, th] = targetDims(width, height)
    return sharp(input, { limitInputPixels: LIMIT_INPUT_PIXELS })
        .resize(tw, th, { fit: 'fill' })
        .blur(BLUR_SIGMA)
        .png()
        .toBuffer()
}

// These params must stay in sync with nodejs/.../anonymize/blur.ts, or the mirror diverges from the inline anonymizer.
import sharp from 'sharp'

const DOWNSAMPLE_RATIO = 0.12
const BLUR_SIGMA = 2.34
const MAX_LONG_SIDE = 96
// Cap decoded pixels: compressed bytes expand many-fold in libvips, so this guards RSS, not input size.
const LIMIT_INPUT_PIXELS = 50_000_000

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
    if (!width || !height) {
        throw new UndecodableImageError('image has invalid dimensions')
    }
    const [tw, th] = targetDims(width, height)
    return sharp(input, { limitInputPixels: LIMIT_INPUT_PIXELS })
        .resize(tw, th, { fit: 'fill' })
        .blur(BLUR_SIGMA)
        .png()
        .toBuffer()
}

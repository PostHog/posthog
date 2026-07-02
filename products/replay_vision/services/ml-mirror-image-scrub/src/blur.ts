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

function targetDims(w: number, h: number): [number, number] {
    const scale = Math.min(DOWNSAMPLE_RATIO, MAX_LONG_SIDE / Math.max(w, h))
    return [Math.max(1, Math.round(w * scale)), Math.max(1, Math.round(h * scale))]
}

export async function blurOnly(input: Buffer): Promise<Buffer> {
    const meta = await sharp(input, { limitInputPixels: LIMIT_INPUT_PIXELS }).metadata()
    const [tw, th] = targetDims(meta.width ?? 1, meta.height ?? 1)
    return sharp(input, { limitInputPixels: LIMIT_INPUT_PIXELS })
        .resize(tw, th, { fit: 'fill' })
        .blur(BLUR_SIGMA)
        .png()
        .toBuffer()
}

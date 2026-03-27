/**
 * Canonical bitmap hashing.
 *
 * Decodes PNG to raw RGBA pixel buffer, then hashes the pixels with BLAKE3.
 * This ensures identical visual content = identical hash,
 * regardless of PNG compression settings, color mode, or metadata.
 *
 * Pipeline: PNG → sRGB colorspace → ensure alpha → raw RGBA → BLAKE3
 * This normalizes greyscale, palette, and other color modes to a
 * consistent 4-channel RGBA layout before hashing.
 *
 * Uses sharp (native libvips) for fast PNG decode.
 */
import { Blake3Hasher } from '@napi-rs/blake-hash'
import sharp from 'sharp'

function toRgba(pngData: Buffer): sharp.Sharp {
    return sharp(pngData).toColorspace('srgb').ensureAlpha().raw()
}

/**
 * Hash PNG image data by decoding to RGBA and hashing the pixel buffer.
 * Returns hex-encoded BLAKE3 hash.
 */
export async function hashImage(pngData: Buffer): Promise<string> {
    const { data, info } = await toRgba(pngData).toBuffer({ resolveWithObject: true })
    if (info.channels !== 4) {
        throw new Error(`Expected 4 channels (RGBA), got ${info.channels}`)
    }
    const hasher = new Blake3Hasher()
    hasher.update(data as unknown as Uint8Array)
    return hasher.digest('hex')
}

/**
 * Get image dimensions from PNG data.
 */
export async function getImageDimensions(pngData: Buffer): Promise<{ width: number; height: number }> {
    const { info } = await toRgba(pngData).toBuffer({ resolveWithObject: true })
    return { width: info.width, height: info.height }
}

/**
 * Hash image and get dimensions in one pass.
 */
export async function hashImageWithDimensions(
    pngData: Buffer
): Promise<{ hash: string; width: number; height: number }> {
    const { data, info } = await toRgba(pngData).toBuffer({ resolveWithObject: true })
    if (info.channels !== 4) {
        throw new Error(`Expected 4 channels (RGBA), got ${info.channels}`)
    }
    const hasher = new Blake3Hasher()
    hasher.update(data as unknown as Uint8Array)
    return {
        hash: hasher.digest('hex'),
        width: info.width,
        height: info.height,
    }
}

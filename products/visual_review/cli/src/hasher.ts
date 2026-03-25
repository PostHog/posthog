/**
 * Canonical bitmap hashing.
 *
 * Decodes PNG to raw RGBA pixel buffer, then hashes the pixels with BLAKE3.
 * This ensures identical visual content = identical hash,
 * regardless of PNG compression settings or metadata.
 *
 * Uses sharp (native libvips) for fast PNG decode.
 */
import { Blake3Hasher } from '@napi-rs/blake-hash'
import sharp from 'sharp'

/**
 * Hash PNG image data by decoding to RGBA and hashing the pixel buffer.
 * Returns hex-encoded BLAKE3 hash.
 */
export async function hashImage(pngData: Buffer): Promise<string> {
    const { data } = await sharp(pngData).ensureAlpha().raw().toBuffer({ resolveWithObject: true })
    const hasher = new Blake3Hasher()
    hasher.update(data as unknown as Uint8Array)
    return hasher.digest('hex')
}

/**
 * Get image dimensions from PNG data.
 */
export async function getImageDimensions(pngData: Buffer): Promise<{ width: number; height: number }> {
    const metadata = await sharp(pngData).metadata()
    return { width: metadata.width!, height: metadata.height! }
}

/**
 * Hash image and get dimensions in one pass.
 */
export async function hashImageWithDimensions(
    pngData: Buffer
): Promise<{ hash: string; width: number; height: number }> {
    const { data, info } = await sharp(pngData).ensureAlpha().raw().toBuffer({ resolveWithObject: true })
    const hasher = new Blake3Hasher()
    hasher.update(data as unknown as Uint8Array)
    return {
        hash: hasher.digest('hex'),
        width: info.width,
        height: info.height,
    }
}

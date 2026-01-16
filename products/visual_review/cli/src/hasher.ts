/**
 * Canonical bitmap hashing.
 *
 * Decodes PNG to raw RGBA pixel buffer, then hashes the pixels.
 * This ensures identical visual content = identical hash,
 * regardless of PNG compression settings or metadata.
 */
import { createHash } from 'node:crypto'
import sharp from 'sharp'

/**
 * Hash PNG image data by decoding to RGBA and hashing the pixel buffer.
 * Returns hex-encoded SHA256 hash.
 */
export async function hashImage(pngData: Buffer): Promise<string> {
    // Decode PNG to raw RGBA pixel buffer
    const { data } = await sharp(pngData).raw().ensureAlpha().toBuffer({ resolveWithObject: true })

    // Hash the raw RGBA pixels
    const hash = createHash('sha256')
    hash.update(data)

    return hash.digest('hex')
}

/**
 * Get image dimensions from PNG data.
 */
export async function getImageDimensions(pngData: Buffer): Promise<{ width: number; height: number }> {
    const metadata = await sharp(pngData).metadata()
    return {
        width: metadata.width ?? 0,
        height: metadata.height ?? 0,
    }
}

/**
 * Hash image and get dimensions in one pass.
 */
export async function hashImageWithDimensions(
    pngData: Buffer
): Promise<{ hash: string; width: number; height: number }> {
    const { data, info } = await sharp(pngData).raw().ensureAlpha().toBuffer({ resolveWithObject: true })

    const hash = createHash('sha256')
    hash.update(data)

    return {
        hash: hash.digest('hex'),
        width: info.width,
        height: info.height,
    }
}

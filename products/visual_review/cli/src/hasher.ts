/**
 * Canonical bitmap hashing.
 *
 * Decodes PNG to raw RGBA pixel buffer, then hashes the pixels.
 * This ensures identical visual content = identical hash,
 * regardless of PNG compression settings or metadata.
 *
 * Uses pngjs (pure JS) instead of sharp to avoid native binary issues
 * when the CLI is distributed as a tarball across platforms.
 */
import { createHash } from 'node:crypto'
import { PNG } from 'pngjs'

function decodePng(pngData: Buffer): { data: Buffer; width: number; height: number } {
    const png = PNG.sync.read(pngData)
    return { data: png.data, width: png.width, height: png.height }
}

/**
 * Hash PNG image data by decoding to RGBA and hashing the pixel buffer.
 * Returns hex-encoded SHA256 hash.
 */
export async function hashImage(pngData: Buffer): Promise<string> {
    const { data } = decodePng(pngData)
    const hash = createHash('sha256')
    hash.update(data)
    return hash.digest('hex')
}

/**
 * Get image dimensions from PNG data.
 */
export async function getImageDimensions(pngData: Buffer): Promise<{ width: number; height: number }> {
    const { width, height } = decodePng(pngData)
    return { width, height }
}

/**
 * Hash image and get dimensions in one pass.
 */
export async function hashImageWithDimensions(
    pngData: Buffer
): Promise<{ hash: string; width: number; height: number }> {
    const { data, width, height } = decodePng(pngData)

    const hash = createHash('sha256')
    hash.update(data)

    return {
        hash: hash.digest('hex'),
        width,
        height,
    }
}

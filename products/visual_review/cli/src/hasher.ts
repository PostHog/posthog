/**
 * Canonical bitmap hashing.
 *
 * Decodes PNG to raw RGBA pixel buffer, then hashes the pixels with BLAKE3.
 * This ensures identical visual content = identical hash,
 * regardless of PNG compression settings or metadata.
 *
 * Uses pngjs (pure JS) instead of sharp to avoid native binary issues
 * when the CLI is distributed as a tarball across platforms.
 */
import { Blake3Hasher } from '@napi-rs/blake-hash'
import { PNG } from 'pngjs'

function decodePng(pngData: Buffer): { data: Buffer; width: number; height: number } {
    const png = PNG.sync.read(pngData)
    return { data: png.data, width: png.width, height: png.height }
}

/**
 * Hash PNG image data by decoding to RGBA and hashing the pixel buffer.
 * Returns hex-encoded BLAKE3 hash.
 */
export async function hashImage(pngData: Buffer): Promise<string> {
    const { data } = decodePng(pngData)
    const hasher = new Blake3Hasher()
    hasher.update(data)
    return hasher.digest('hex')
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

    const hasher = new Blake3Hasher()
    hasher.update(data)

    return {
        hash: hasher.digest('hex'),
        width,
        height,
    }
}

// NOTE: These functions are meant to be identical to those in posthog/session_recordings/session_recording_helpers.py

// Write a Node.js function that compresses a string using gzip utf-16 surrogatepass and base64 encodes it

import zlib from 'node:zlib'

export function compressToString(input: string): string {
    const compressed_data = zlib.gzipSync(Buffer.from(input, 'utf16le'))
    return compressed_data.toString('base64')
}

export function decompressFromString(input: string): string {
    const compressedData = Buffer.from(input, 'base64')
    const uncompressed = zlib.gunzipSync(compressedData)
    // Trim is quick way to get rid of BOMs created by python
    return uncompressed.toString('utf16le').trim()
}

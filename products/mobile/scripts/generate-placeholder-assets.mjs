// Writes placeholder PNG assets: the three-bar PostHog mark on white. Final artwork is pending.
// Uses only Node built-ins so it runs before `pnpm install`.
import { writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { deflateSync } from 'node:zlib'

const ASSETS = join(dirname(fileURLToPath(import.meta.url)), '..', 'assets')

const BARS = [
    { color: [0xf5, 0x4e, 0x00], height: 10 },
    { color: [0xf9, 0xbd, 0x2b], height: 14 },
    { color: [0x1d, 0x4a, 0xff], height: 18 },
]

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
    let c = n
    for (let k = 0; k < 8; k++) {
        c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    }
    return c >>> 0
})

function crc32(buffer) {
    let crc = 0xffffffff
    for (const byte of buffer) {
        crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8)
    }
    return (crc ^ 0xffffffff) >>> 0
}

function chunk(type, data) {
    const length = Buffer.alloc(4)
    length.writeUInt32BE(data.length)
    const body = Buffer.concat([Buffer.from(type, 'ascii'), data])
    const crc = Buffer.alloc(4)
    crc.writeUInt32BE(crc32(body))
    return Buffer.concat([length, body, crc])
}

/** Draws the mark centered, `scale` canvas pixels per design point, on white or transparent. */
function render(size, scale, transparent) {
    const pixels = Buffer.alloc(size * size * 4, transparent ? 0 : 255)
    const barWidth = 4 * scale
    const gap = 2 * scale
    const radius = scale
    const markWidth = barWidth * 3 + gap * 2
    const markHeight = 18 * scale
    const left = Math.round((size - markWidth) / 2)
    const bottom = Math.round((size + markHeight) / 2)
    BARS.forEach((bar, index) => {
        const x0 = left + index * (barWidth + gap)
        const y0 = bottom - bar.height * scale
        for (let y = y0; y < bottom; y++) {
            for (let x = x0; x < x0 + barWidth; x++) {
                const dx = Math.max(x0 + radius - x - 0.5, x - (x0 + barWidth - radius) + 0.5, 0)
                const dy = Math.max(y0 + radius - y - 0.5, y - (bottom - radius) + 0.5, 0)
                if (dx * dx + dy * dy > radius * radius) {
                    continue
                }
                const offset = (y * size + x) * 4
                pixels[offset] = bar.color[0]
                pixels[offset + 1] = bar.color[1]
                pixels[offset + 2] = bar.color[2]
                pixels[offset + 3] = 255
            }
        }
    })
    const rows = Buffer.alloc(size * (size * 4 + 1))
    for (let y = 0; y < size; y++) {
        pixels.copy(rows, y * (size * 4 + 1) + 1, y * size * 4, (y + 1) * size * 4)
    }
    const header = Buffer.alloc(13)
    header.writeUInt32BE(size, 0)
    header.writeUInt32BE(size, 4)
    header[8] = 8
    header[9] = 6
    return Buffer.concat([
        Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
        chunk('IHDR', header),
        chunk('IDAT', deflateSync(rows)),
        chunk('IEND', Buffer.alloc(0)),
    ])
}

const outputs = [
    ['icon.png', 1024, 24, false],
    ['adaptive-icon.png', 1024, 18, true],
    ['splash-icon.png', 512, 16, true],
    ['favicon.png', 48, 2, false],
]
for (const [name, size, scale, transparent] of outputs) {
    writeFileSync(join(ASSETS, name), render(size, scale, transparent))
}
console.log(`wrote ${outputs.map(([name]) => name).join(', ')}`)

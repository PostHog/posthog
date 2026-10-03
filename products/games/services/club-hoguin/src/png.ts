// Reads and writes PNG files with only node:zlib, so the server needs no image library.
// Reading covers what the hedgehog sprite sheet is: 8 bits per channel, RGBA, not interlaced.
import { crc32, deflateSync, inflateSync } from 'node:zlib'

export interface RgbaImage {
    width: number
    height: number
    data: Uint8Array
}

const SIGNATURE = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])

export function decodePng(file: Buffer): RgbaImage {
    if (!file.subarray(0, 8).equals(SIGNATURE)) {
        throw new Error('not a PNG file')
    }
    let width = 0
    let height = 0
    const compressed: Buffer[] = []
    for (let offset = 8; offset < file.length; ) {
        const length = file.readUInt32BE(offset)
        const type = file.toString('latin1', offset + 4, offset + 8)
        const body = file.subarray(offset + 8, offset + 8 + length)
        if (type === 'IHDR') {
            width = body.readUInt32BE(0)
            height = body.readUInt32BE(4)
            const [depth, color, interlace] = [body[8], body[9], body[12]]
            if (depth !== 8 || color !== 6 || interlace !== 0) {
                throw new Error(`unsupported PNG: depth ${depth}, color type ${color}, interlace ${interlace}`)
            }
        } else if (type === 'IDAT') {
            compressed.push(body)
        }
        offset += 12 + length
    }
    const raw = inflateSync(Buffer.concat(compressed))
    const stride = width * 4
    const data = new Uint8Array(stride * height)
    for (let row = 0; row < height; row++) {
        const filter = raw[row * (stride + 1)]
        const line = raw.subarray(row * (stride + 1) + 1, (row + 1) * (stride + 1))
        const out = row * stride
        for (let index = 0; index < stride; index++) {
            const left = index >= 4 ? data[out + index - 4]! : 0
            const up = row > 0 ? data[out - stride + index]! : 0
            const upLeft = row > 0 && index >= 4 ? data[out - stride + index - 4]! : 0
            let predicted = 0
            if (filter === 1) {
                predicted = left
            } else if (filter === 2) {
                predicted = up
            } else if (filter === 3) {
                predicted = (left + up) >> 1
            } else if (filter === 4) {
                const estimate = left + up - upLeft
                const dLeft = Math.abs(estimate - left)
                const dUp = Math.abs(estimate - up)
                const dUpLeft = Math.abs(estimate - upLeft)
                predicted = dLeft <= dUp && dLeft <= dUpLeft ? left : dUp <= dUpLeft ? up : upLeft
            }
            data[out + index] = (line[index]! + predicted) & 255
        }
    }
    return { width, height, data }
}

function chunk(type: string, body: Buffer): Buffer {
    const length = Buffer.alloc(4)
    length.writeUInt32BE(body.length)
    const typed = Buffer.concat([Buffer.from(type, 'latin1'), body])
    const crc = Buffer.alloc(4)
    crc.writeUInt32BE(crc32(typed))
    return Buffer.concat([length, typed, crc])
}

export function encodePng(image: RgbaImage): Buffer {
    const header = Buffer.alloc(13)
    header.writeUInt32BE(image.width, 0)
    header.writeUInt32BE(image.height, 4)
    header[8] = 8
    header[9] = 6
    const stride = image.width * 4
    const raw = Buffer.alloc((stride + 1) * image.height)
    for (let row = 0; row < image.height; row++) {
        raw[row * (stride + 1)] = 0
        raw.set(image.data.subarray(row * stride, (row + 1) * stride), row * (stride + 1) + 1)
    }
    return Buffer.concat([
        SIGNATURE,
        chunk('IHDR', header),
        chunk('IDAT', deflateSync(raw, { level: 4 })),
        chunk('IEND', Buffer.alloc(0)),
    ])
}

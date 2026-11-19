import { readFileSync, writeFileSync } from 'node:fs'

// Writes the Live world map's country outlines from the web's Robinson projection map, one `d` string per ISO
// 3166-1 alpha-2 code. Run it with `pnpm map:generate` after the web's countryVectors.tsx changes.

const root = new URL('../', import.meta.url)
const source = new URL('../product_analytics/frontend/insights/trends/WorldMap/countryVectors.tsx', root)
const destination = new URL('src/features/live/map/worldPaths.ts', root)

const TOKEN = /[MmLlHhVvCcZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?/g
const ENTRY = /\n {4}([A-Z]{2}|[A-Za-z_]+): \(/
const PATH_DATA = /\sd="([^"]+)"/g

function joinNumbers(values) {
    return values.reduce((text, value) => {
        const number = String(value)
        return text === '' || number.startsWith('-') ? text + number : `${text} ${number}`
    }, '')
}

/**
 * Writes one country's sub-paths as a single `d`. The source starts every sub-path with a relative `m`, which a plain
 * join reads as an offset from the end of the previous sub-path and so moves islands. The encoder works in absolute
 * points rounded to integers and writes each command as the delta between rounded points, so rounding never drifts.
 */
class Encoder {
    parts = []
    x = 0
    y = 0
    startX = 0
    startY = 0
    started = false

    move(x, y) {
        const X = Math.round(x)
        const Y = Math.round(y)
        this.parts.push(this.started ? ['m', [X - this.x, Y - this.y]] : ['M', [X, Y]])
        this.started = true
        this.x = this.startX = X
        this.y = this.startY = Y
    }

    line(x, y) {
        const X = Math.round(x)
        const Y = Math.round(y)
        if (X !== this.x || Y !== this.y) {
            this.parts.push(['l', [X - this.x, Y - this.y]])
            this.x = X
            this.y = Y
        }
    }

    curve(x1, y1, x2, y2, x, y) {
        const points = [x1, y1, x2, y2, x, y].map(Math.round)
        const deltas = points.map((value, index) => value - (index % 2 === 0 ? this.x : this.y))
        if (deltas.some((delta) => delta !== 0)) {
            this.parts.push(['c', deltas])
            this.x = points[4]
            this.y = points[5]
        }
    }

    close() {
        this.parts.push(['z', []])
        this.x = this.startX
        this.y = this.startY
    }

    text() {
        let text = ''
        let last = null
        for (const [command, values] of this.parts) {
            const numbers = joinNumbers(values)
            if (command === last && (command === 'l' || command === 'c')) {
                text += numbers.startsWith('-') ? numbers : ` ${numbers}`
            } else {
                text += command + numbers
            }
            last = command === 'z' ? null : command
        }
        return text
    }
}

function encode(d, encoder) {
    const tokens = d.match(TOKEN) ?? []
    let index = 0
    let command = null
    let x = 0
    let y = 0
    let startX = 0
    let startY = 0
    let firstMove = true
    const next = () => Number(tokens[index++])
    while (index < tokens.length) {
        if (/[A-Za-z]/.test(tokens[index])) {
            command = tokens[index++]
            if (command === 'z' || command === 'Z') {
                x = startX
                y = startY
                encoder.close()
                continue
            }
        }
        const relative = command === command?.toLowerCase()
        switch (command) {
            case 'm':
            case 'M': {
                let mx = next()
                let my = next()
                // The first `m` of a `d` is absolute, as the SVG spec says.
                if (relative && !firstMove) {
                    mx += x
                    my += y
                }
                firstMove = false
                x = startX = mx
                y = startY = my
                encoder.move(x, y)
                command = relative ? 'l' : 'L'
                break
            }
            case 'l':
            case 'L': {
                const lx = next()
                const ly = next()
                x = relative ? x + lx : lx
                y = relative ? y + ly : ly
                encoder.line(x, y)
                break
            }
            case 'h':
            case 'H': {
                const hx = next()
                x = relative ? x + hx : hx
                encoder.line(x, y)
                break
            }
            case 'v':
            case 'V': {
                const vy = next()
                y = relative ? y + vy : vy
                encoder.line(x, y)
                break
            }
            case 'c':
            case 'C': {
                const values = Array.from({ length: 6 }, next)
                const absolute = relative ? values.map((value, i) => value + (i % 2 === 0 ? x : y)) : values
                encoder.curve(...absolute)
                x = absolute[4]
                y = absolute[5]
                break
            }
            default:
                throw new Error(`Unsupported path command ${command}`)
        }
    }
}

const entries = readFileSync(source, 'utf8').split(ENTRY)
const paths = []
for (let index = 1; index < entries.length; index += 2) {
    const code = entries[index]
    const body = entries[index + 1]
    if (!/^[A-Z]{2}$/.test(code)) {
        continue
    }
    const encoder = new Encoder()
    for (const [, d] of body.matchAll(PATH_DATA)) {
        encode(d, encoder)
    }
    if (encoder.started) {
        paths.push([code, encoder.text()])
    }
}
paths.sort(([a], [b]) => (a < b ? -1 : 1))

const output = `// Generated by scripts/generate-world-map.mjs from the web's countryVectors.tsx. Run \`pnpm map:generate\` to update it.
// The paths use the source's 2754 × 1200 viewBox.

export const WORLD_PATHS: Readonly<Record<string, string>> = {
${paths.map(([code, d]) => `    ${code}: '${d}',`).join('\n')}
}
`
writeFileSync(destination, output)
console.log(`${paths.length} countries, ${output.length} bytes`)

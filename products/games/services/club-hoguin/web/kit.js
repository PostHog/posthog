// Small building blocks for the town: materials, shapes, and signs drawn on a canvas.
import * as THREE from '/vendor/three/three.module.min.js'

export { THREE }

export const COLORS = {
    snow: 0xf4f8fc,
    snowShade: 0xd6e4f2,
    ice: 0xbfe6fa,
    wood: 0x8a5a3c,
    woodDark: 0x5e3b27,
    stone: 0x8b95a5,
    pine: 0x2f6b4f,
    pineDark: 0x24553f,
    ink: 0x151515,
    orange: 0xf54e00,
    blue: 0x1d4aff,
    yellow: 0xf9bd2b,
    purple: 0xb62ad9,
    teal: 0x30abc6,
    green: 0x2ba84a,
    red: 0xe5383b,
    cream: 0xfff6e5,
}

export const SIGN_FONT = '"Arial Rounded MT Bold", "Nunito", "Trebuchet MS", system-ui, sans-serif'

/** @param {number} color @param {object} [options] */
export function mat(color, options = {}) {
    return new THREE.MeshStandardMaterial({ color, flatShading: true, roughness: 0.9, metalness: 0, ...options })
}

// Materials that glow at night. The town sets their strength from the time of day.
/** @type {Array<{ material: THREE.MeshStandardMaterial, day: number, night: number }>} */
export const glowMaterials = []

/** @param {number} color @param {number} day @param {number} night @param {object} [options] */
export function glow(color, day, night, options = {}) {
    const material = mat(color, { emissive: color, emissiveIntensity: day, ...options })
    glowMaterials.push({ material, day, night })
    return material
}

/**
 * @param {THREE.BufferGeometry} geometry
 * @param {THREE.Material} material
 * @param {[number, number, number]} position
 * @param {{ cast?: boolean, receive?: boolean, rotation?: [number, number, number], scale?: [number, number, number] }} [options]
 */
export function mesh(geometry, material, position, options = {}) {
    const result = new THREE.Mesh(geometry, material)
    result.position.set(...position)
    if (options.rotation) {
        result.rotation.set(...options.rotation)
    }
    if (options.scale) {
        result.scale.set(...options.scale)
    }
    result.castShadow = options.cast ?? true
    result.receiveShadow = options.receive ?? true
    return result
}

export const box = (/** @type {number} */ w, /** @type {number} */ h, /** @type {number} */ d) =>
    new THREE.BoxGeometry(w, h, d)
export const cylinder = (
    /** @type {number} */ top,
    /** @type {number} */ bottom,
    /** @type {number} */ h,
    /** @type {number} */ segments = 12
) => new THREE.CylinderGeometry(top, bottom, h, segments)
export const cone = (/** @type {number} */ r, /** @type {number} */ h, /** @type {number} */ segments = 10) =>
    new THREE.ConeGeometry(r, h, segments)
export const sphere = (/** @type {number} */ r, /** @type {number} */ detail = 1) =>
    new THREE.IcosahedronGeometry(r, detail)

/**
 * A flat board that shows a canvas drawing. Call redraw to change what it shows.
 * @param {number} width board width in units
 * @param {number} height board height in units
 * @param {number} pixelsPerUnit
 * @param {(g: CanvasRenderingContext2D, w: number, h: number) => void} draw
 */
export function sign(width, height, pixelsPerUnit, draw) {
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(width * pixelsPerUnit)
    canvas.height = Math.round(height * pixelsPerUnit)
    const g = /** @type {CanvasRenderingContext2D} */ (canvas.getContext('2d'))
    const texture = new THREE.CanvasTexture(canvas)
    texture.colorSpace = THREE.SRGBColorSpace
    texture.anisotropy = 4
    const board = new THREE.Mesh(
        new THREE.PlaneGeometry(width, height),
        new THREE.MeshBasicMaterial({ map: texture, transparent: true, toneMapped: false })
    )
    const redraw = (/** @type {typeof draw} */ next = draw) => {
        g.clearRect(0, 0, canvas.width, canvas.height)
        next(g, canvas.width, canvas.height)
        texture.needsUpdate = true
    }
    redraw()
    return { board, redraw }
}

/** @param {CanvasRenderingContext2D} g */
export function roundedPanel(g, x, y, w, h, radius, fill, stroke, lineWidth = 6) {
    g.beginPath()
    g.roundRect(x, y, w, h, radius)
    g.fillStyle = fill
    g.fill()
    if (stroke) {
        g.lineWidth = lineWidth
        g.strokeStyle = stroke
        g.stroke()
    }
}

// Draws text that shrinks to fit the given width, and wraps onto at most maxLines lines.
/** @param {CanvasRenderingContext2D} g */
export function fitText(g, text, centerX, centerY, maxWidth, size, color, maxLines = 1, weight = 'bold') {
    g.fillStyle = color
    g.textAlign = 'center'
    g.textBaseline = 'middle'
    let lines = [text]
    let fontSize = size
    for (; fontSize > 8; fontSize -= 2) {
        g.font = `${weight} ${fontSize}px ${SIGN_FONT}`
        lines = wrap(g, text, maxWidth)
        if (lines.length <= maxLines && lines.every((line) => g.measureText(line).width <= maxWidth)) {
            break
        }
    }
    const lineHeight = fontSize * 1.18
    lines.slice(0, maxLines).forEach((line, index) => {
        g.fillText(line, centerX, centerY + (index - (Math.min(lines.length, maxLines) - 1) / 2) * lineHeight)
    })
}

/** @param {CanvasRenderingContext2D} g @param {string} text @param {number} maxWidth */
function wrap(g, text, maxWidth) {
    const lines = []
    let line = ''
    for (const word of text.split(' ')) {
        const candidate = line ? `${line} ${word}` : word
        if (line && g.measureText(candidate).width > maxWidth) {
            lines.push(line)
            line = word
        } else {
            line = candidate
        }
    }
    lines.push(line)
    return lines
}

// A snow cap for a flat roof: a white slab with soft lumps on it.
/** @param {number} w @param {number} d */
export function snowCap(w, d, lumps = 5) {
    const group = new THREE.Group()
    const snow = mat(COLORS.snow, { flatShading: false, roughness: 1 })
    group.add(mesh(box(w + 0.3, 0.22, d + 0.3), snow, [0, 0.11, 0]))
    for (let index = 0; index < lumps; index++) {
        const along = (index + 0.5) / lumps - 0.5
        group.add(
            mesh(sphere(0.5, 2), snow, [along * w, 0.2, Math.sin(index * 2.4) * d * 0.25], {
                scale: [w / lumps / 0.8, 0.35, d * 0.42],
            })
        )
    }
    return group
}

// A pine tree with snow on its branches.
/** @param {number} height */
export function pine(height, dark = false) {
    const group = new THREE.Group()
    const green = mat(dark ? COLORS.pineDark : COLORS.pine)
    const snow = mat(COLORS.snow, { roughness: 1 })
    group.add(mesh(cylinder(0.16, 0.22, height * 0.25, 6), mat(COLORS.woodDark), [0, height * 0.12, 0]))
    for (let tier = 0; tier < 3; tier++) {
        const radius = height * (0.34 - tier * 0.08)
        const y = height * (0.38 + tier * 0.22)
        group.add(mesh(cone(radius, height * 0.4, 8), green, [0, y, 0]))
        group.add(mesh(cone(radius * 0.62, height * 0.2, 8), snow, [0, y + height * 0.11, 0], { cast: false }))
    }
    return group
}

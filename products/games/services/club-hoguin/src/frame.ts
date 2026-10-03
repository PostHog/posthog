// Paints the town as a small picture, for a Claude Code pane that can show pictures but not run three.js.
// The painter has no font, so the picture carries no words; the pane writes those as text under it.
import { CAMPFIRE, DECORATIONS, LAB_FOOTPRINT, OBJECTS, POND, WORLD_DEPTH, WORLD_WIDTH } from './content.ts'
import { encodePng, type RgbaImage } from './png.ts'
import type { PlayerView, Snapshot } from './world.ts'

export const PIXELS_PER_UNIT = 12
export const FRAME_WIDTH = WORLD_WIDTH * PIXELS_PER_UNIT
export const FRAME_HEIGHT = WORLD_DEPTH * PIXELS_PER_UNIT
// Hedgehog sprites are 80 pixels tall; in the picture a hedgehog is about three units.
const SPRITE_SIZE = 3.4 * PIXELS_PER_UNIT
const FRAME_INTERVAL_MS = 100

type Rgb = readonly [number, number, number]
const rgb = (hex: number): Rgb => [hex >> 16, (hex >> 8) & 255, hex & 255]

const SNOW = rgb(0xeef3fa)
const NIGHT_SNOW = rgb(0x3b4a7a)
const TREE_SPOTS: ReadonlyArray<readonly [number, number, number]> = [
    [-0.5, 1.5, 1.6],
    [7.4, 0.2, 1.5],
    [19.9, 0.4, 1.4],
    [30.4, 0.3, 1.5],
    [39.6, 2.4, 1.4],
    [0.3, 7, 1.4],
    [0.2, 14, 1.5],
    [0.4, 18.5, 1.3],
    [39.7, 7, 1.4],
    [39.6, 11, 1.5],
    [39.7, 15.5, 1.3],
    [39.5, 19.5, 1.4],
]
const LAMPS: ReadonlyArray<readonly [number, number]> = [
    [19.9, 4.3],
    [30.4, 4.3],
    [0.3, 12],
    [39.7, 12],
    [0.3, 20.4],
    [39.7, 20.4],
]

interface Frame {
    name: string
    x: number
    y: number
    w: number
    h: number
}

export interface SpriteAtlas {
    image: RgbaImage
    frames: Record<string, { frame: { x: number; y: number; w: number; h: number } }>
}

export class FramePainter {
    private readonly atlas: SpriteAtlas
    private readonly animations = new Map<string, Frame[]>()
    private cache: { key: string; png: Buffer } | null = null

    constructor(atlas: SpriteAtlas) {
        this.atlas = atlas
        for (const name of Object.keys(atlas.frames).sort()) {
            const animation = name.slice(0, name.lastIndexOf('/'))
            const list = this.animations.get(animation) ?? []
            list.push({ name, ...atlas.frames[name]!.frame })
            this.animations.set(animation, list)
        }
    }

    // One picture per quarter second serves every pane that asks in that time.
    paint(snapshot: Snapshot, viewerId: string | null, now: number): Buffer {
        const key = `${snapshot.seq}:${Math.floor(now / FRAME_INTERVAL_MS)}:${viewerId ?? ''}`
        if (this.cache?.key === key) {
            return this.cache.png
        }
        const png = encodePng(this.draw(snapshot, viewerId, now))
        this.cache = { key, png }
        return png
    }

    private draw(snapshot: Snapshot, viewerId: string | null, now: number): RgbaImage {
        const night = !snapshot.objects.lightsOn
        const image: RgbaImage = {
            width: FRAME_WIDTH,
            height: FRAME_HEIGHT,
            data: new Uint8Array(FRAME_WIDTH * FRAME_HEIGHT * 4),
        }
        const canvas = new Canvas(image, night)
        canvas.fill(night ? NIGHT_SNOW : SNOW)
        // The street along the buildings and the plaza around the fire are packed snow.
        canvas.rect(2, 5.2, 36, 2, rgb(0xd5e1ef))
        canvas.ellipse(CAMPFIRE.x, CAMPFIRE.y, 3.6, 3.6, rgb(0xd5e1ef))
        canvas.ellipse(POND.x, POND.y, POND.rx + 0.4, POND.ry + 0.4, rgb(0xffffff))
        canvas.ellipse(POND.x, POND.y, POND.rx, POND.ry, rgb(night ? 0x5b86c8 : 0xbfe6fa))
        for (const [x, y, radius] of TREE_SPOTS) {
            canvas.ellipse(x, y + 0.3, radius, radius * 0.9, rgb(0x2f6b4f))
            canvas.ellipse(x, y - 0.3, radius * 0.6, radius * 0.5, rgb(0xffffff))
        }
        // Buildings, as blocks of their color with snow on the roof and a dark front.
        this.building(canvas, 'flag', rgb(0xf9bd2b), rgb(0xffffff))
        this.building(canvas, 'replay', rgb(0x1d4aff), rgb(0x101426))
        canvas.rect(LAB_FOOTPRINT.x, LAB_FOOTPRINT.y, LAB_FOOTPRINT.w, LAB_FOOTPRINT.h, rgb(0xe9f3f6))
        canvas.rect(LAB_FOOTPRINT.x, LAB_FOOTPRINT.y, LAB_FOOTPRINT.w, 0.6, rgb(0x30abc6))
        for (const id of ['door-a', 'door-b'] as const) {
            const door = OBJECTS.find((object) => object.id === id)!
            canvas.rect(
                door.footprint.x + 0.3,
                door.footprint.y - 1.2,
                door.footprint.w - 0.6,
                2.2,
                rgb(id === 'door-a' ? 0x30abc6 : 0xf54e00)
            )
        }
        this.building(canvas, 'max', rgb(0xb62ad9), rgb(0x8a5a3c))
        const jar = OBJECTS.find((object) => object.id === 'bugs')!.footprint
        canvas.rect(jar.x, jar.y, jar.w, jar.h, rgb(0x8fd3f4))
        canvas.rect(jar.x + 0.2, jar.y - 0.4, jar.w - 0.4, 0.5, rgb(0xf54e00))
        const pad = OBJECTS.find((object) => object.id === 'ship')!.footprint
        canvas.ellipse(pad.x + pad.w / 2, pad.y + pad.h / 2, pad.w / 2, pad.h / 2, rgb(0x4a5162))
        canvas.rect(pad.x + pad.w / 2 - 0.6, pad.y - 0.6, 1.2, 2.6, rgb(0xffffff))
        canvas.rect(pad.x + pad.w / 2 - 0.6, pad.y - 1.2, 1.2, 0.7, rgb(0xf54e00))
        canvas.ellipse(pad.x + pad.w / 2, pad.y + pad.h + 0.3, 0.45, 0.45, rgb(0xe5383b))
        for (const decoration of DECORATIONS) {
            if (decoration.kind === 'tree') {
                canvas.ellipse(decoration.x, decoration.y + 0.2, 1.1, 1, rgb(0x2f6b4f))
                canvas.ellipse(decoration.x, decoration.y - 0.4, 0.6, 0.5, rgb(0xffffff))
            } else if (decoration.kind === 'snowman') {
                canvas.ellipse(decoration.x, decoration.y, 0.8, 0.7, rgb(0xffffff))
                canvas.ellipse(decoration.x, decoration.y - 1.1, 0.5, 0.5, rgb(0xffffff))
                canvas.rect(decoration.x, decoration.y - 1.2, 0.4, 0.15, rgb(0xf54e00))
            } else if (decoration.kind === 'bench') {
                canvas.rect(decoration.x - 0.35, decoration.y - 1, 0.7, 2, rgb(0x8a5a3c))
            } else {
                canvas.rect(decoration.x - 0.1, decoration.y - 1.5, 0.2, 1.6, rgb(0x5e3b27))
                canvas.rect(decoration.x - 0.9, decoration.y - 1.6, 1.8, 0.45, rgb(0x2ba84a))
            }
        }
        for (let x = 0.5; x <= 39.5; x += 3) {
            canvas.rect(x - 0.1, 21.6, 0.2, 0.7, rgb(0x8a5a3c))
        }
        canvas.rect(0.5, 21.8, 39, 0.15, rgb(0x8a5a3c))
        // The fire, with a bigger flame on the beats of the clock.
        canvas.ellipse(CAMPFIRE.x, CAMPFIRE.y, 1.2, 1.2, rgb(0x8b95a5))
        canvas.ellipse(CAMPFIRE.x, CAMPFIRE.y, 0.7, 0.7 + ((now / FRAME_INTERVAL_MS) % 2) * 0.2, rgb(0xff7a1a))
        canvas.ellipse(CAMPFIRE.x, CAMPFIRE.y - 0.1, 0.35, 0.4, rgb(0xffc93c))
        if (night) {
            for (const [x, y] of LAMPS) {
                canvas.glow(x, y, 3.2, rgb(0xffd39a))
            }
            canvas.glow(CAMPFIRE.x, CAMPFIRE.y, 4.5, rgb(0xff9a3c))
        }
        for (const [x, y] of LAMPS) {
            canvas.ellipse(x, y, 0.35, 0.35, rgb(night ? 0xffe2a8 : 0x2b3040))
        }
        // Hedgehogs, farthest first so a nearer one draws over a farther one.
        const players = [...snapshot.players].sort((a, b) => a.y - b.y)
        for (const player of players) {
            canvas.ellipse(player.x, player.y + 0.1, 0.9, 0.35, rgb(night ? 0x2a3560 : 0xc9d6e8))
            this.sprite(canvas, player, now)
            if (player.id === viewerId) {
                canvas.rect(player.x - 0.25, player.y - 4.3, 0.5, 0.9, rgb(0xf54e00))
            }
        }
        return image
    }

    private building(canvas: Canvas, id: string, color: Rgb, front: Rgb): void {
        const { x, y, w, h } = OBJECTS.find((object) => object.id === id)!.footprint
        canvas.rect(x, y, w, h, color)
        canvas.rect(x, y, w, 0.7, rgb(0xffffff))
        canvas.rect(x + w * 0.3, y + h - 0.9, w * 0.4, 0.9, front)
    }

    private sprite(canvas: Canvas, player: PlayerView, now: number): void {
        const frames =
            this.animations.get(`skins/${player.skin}/${player.moving ? 'walk' : 'idle'}`) ??
            this.animations.get(`skins/${player.skin}/idle`) ??
            []
        const frame = frames[Math.floor(now / 80) % Math.max(1, frames.length)]
        if (!frame) {
            return
        }
        const scale = SPRITE_SIZE / frame.h
        const left = player.x * PIXELS_PER_UNIT - SPRITE_SIZE / 2
        const top = player.y * PIXELS_PER_UNIT - SPRITE_SIZE * 0.94
        const flip = player.facing === 'left'
        this.layer(canvas, frame, left, top, scale, flip)
        const hat = player.hat ? this.atlas.frames[`accessories/${player.hat}.png`]?.frame : undefined
        if (hat) {
            // The head dips on every other walk frame, and the hat goes with it.
            const dip = player.moving && Math.floor(now / 80) % 2 ? 1 : 0
            this.layer(canvas, hat, left, top + dip, scale, flip)
        }
    }

    private layer(
        canvas: Canvas,
        frame: { x: number; y: number; w: number; h: number },
        left: number,
        top: number,
        scale: number,
        flip: boolean
    ): void {
        for (let py = 0; py < SPRITE_SIZE; py++) {
            const sy = frame.y + Math.floor(py / scale)
            for (let px = 0; px < SPRITE_SIZE; px++) {
                const sx = frame.x + Math.floor((flip ? SPRITE_SIZE - 1 - px : px) / scale)
                const source = (sy * this.atlas.image.width + sx) * 4
                if (this.atlas.image.data[source + 3]! > 128) {
                    canvas.pixel(Math.floor(left + px), Math.floor(top + py), [
                        this.atlas.image.data[source]!,
                        this.atlas.image.data[source + 1]!,
                        this.atlas.image.data[source + 2]!,
                    ])
                }
            }
        }
    }
}

// Drawing in town units onto the picture. At night every color is darker and bluer.
class Canvas {
    private readonly image: RgbaImage
    private readonly night: boolean

    constructor(image: RgbaImage, night: boolean) {
        this.image = image
        this.night = night
    }

    fill(color: Rgb): void {
        for (let index = 0; index < this.image.data.length; index += 4) {
            this.image.data.set([color[0], color[1], color[2], 255], index)
        }
    }

    pixel(px: number, py: number, color: Rgb): void {
        if (px < 0 || py < 0 || px >= this.image.width || py >= this.image.height) {
            return
        }
        const index = (py * this.image.width + px) * 4
        const dim = this.night ? 0.55 : 1
        this.image.data[index] = color[0] * dim
        this.image.data[index + 1] = color[1] * dim
        this.image.data[index + 2] = Math.min(255, color[2] * dim + (this.night ? 40 : 0))
        this.image.data[index + 3] = 255
    }

    rect(x: number, y: number, w: number, h: number, color: Rgb): void {
        for (let py = Math.round(y * PIXELS_PER_UNIT); py < Math.round((y + h) * PIXELS_PER_UNIT); py++) {
            for (let px = Math.round(x * PIXELS_PER_UNIT); px < Math.round((x + w) * PIXELS_PER_UNIT); px++) {
                this.pixel(px, py, color)
            }
        }
    }

    ellipse(x: number, y: number, rx: number, ry: number, color: Rgb): void {
        for (let py = Math.floor((y - ry) * PIXELS_PER_UNIT); py <= Math.ceil((y + ry) * PIXELS_PER_UNIT); py++) {
            for (let px = Math.floor((x - rx) * PIXELS_PER_UNIT); px <= Math.ceil((x + rx) * PIXELS_PER_UNIT); px++) {
                const dx = (px + 0.5) / PIXELS_PER_UNIT - x
                const dy = (py + 0.5) / PIXELS_PER_UNIT - y
                if ((dx * dx) / (rx * rx) + (dy * dy) / (ry * ry) <= 1) {
                    this.pixel(px, py, color)
                }
            }
        }
    }

    // Warm light that fades with distance, added on top of what is there.
    glow(x: number, y: number, radius: number, color: Rgb): void {
        for (
            let py = Math.floor((y - radius) * PIXELS_PER_UNIT);
            py <= Math.ceil((y + radius) * PIXELS_PER_UNIT);
            py++
        ) {
            for (
                let px = Math.floor((x - radius) * PIXELS_PER_UNIT);
                px <= Math.ceil((x + radius) * PIXELS_PER_UNIT);
                px++
            ) {
                if (px < 0 || py < 0 || px >= this.image.width || py >= this.image.height) {
                    continue
                }
                const distance = Math.hypot((px + 0.5) / PIXELS_PER_UNIT - x, (py + 0.5) / PIXELS_PER_UNIT - y)
                const strength = Math.max(0, 1 - distance / radius) * 0.55
                const index = (py * this.image.width + px) * 4
                for (let channel = 0; channel < 3; channel++) {
                    this.image.data[index + channel] = Math.min(
                        255,
                        this.image.data[index + channel]! + color[channel]! * strength
                    )
                }
            }
        }
    }
}

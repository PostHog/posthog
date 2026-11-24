export const HOG_ANIMATIONS = ['walk', 'idle', 'jump', 'fall', 'wave', 'flag'] as const

export type HogAnimation = (typeof HOG_ANIMATIONS)[number]

export interface HogFrame {
    x: number
    y: number
    w: number
    h: number
}

export interface HogSprites {
    image: HTMLImageElement
    animations: Record<HogAnimation, HogFrame[]>
    accessories: Record<string, HogFrame>
}

interface SpriteSheet {
    frames: Record<string, { frame: HogFrame }>
    animations: Record<string, string[]>
}

let spritesPromise: Promise<HogSprites> | null = null

function loadImage(src: string): Promise<HTMLImageElement> {
    return new Promise((resolve, reject) => {
        const image = new Image()
        image.onload = () => resolve(image)
        image.onerror = () => reject(new Error(`Could not load ${src}`))
        image.src = src
    })
}

async function loadSheet(src: string): Promise<SpriteSheet> {
    const response = await fetch(src)
    if (!response.ok) {
        throw new Error(`Could not load ${src}`)
    }
    return (await response.json()) as SpriteSheet
}

function toSprites(sheet: SpriteSheet, image: HTMLImageElement): HogSprites {
    const animations = Object.fromEntries(
        HOG_ANIMATIONS.map((animation) => {
            const frames = sheet.animations[`skins/default/${animation}/tile`]
            if (!frames?.length) {
                throw new Error(`The sprite sheet has no ${animation} animation`)
            }
            return [animation, frames.map((name) => sheet.frames[name].frame)]
        })
    ) as Record<HogAnimation, HogFrame[]>
    const accessories = Object.fromEntries(
        Object.entries(sheet.frames)
            .filter(([name]) => name.startsWith('accessories/'))
            .map(([name, { frame }]) => [name.slice('accessories/'.length, -'.png'.length), frame])
    )
    return { image, animations, accessories }
}

export function loadHogSprites(assetsUrl: string): Promise<HogSprites> {
    if (!spritesPromise) {
        spritesPromise = Promise.all([loadSheet(`${assetsUrl}/sprites.json`), loadImage(`${assetsUrl}/sprites.png`)])
            .then(([sheet, image]) => toSprites(sheet, image))
            .catch((error) => {
                spritesPromise = null
                throw error
            })
    }
    return spritesPromise
}

import { HogWorld, SeasonalHog } from './seasonalHog'
import { HOG_ANIMATIONS, HogSprites } from './seasonalHogSprites'

const FRAME_COUNTS = { walk: 11, idle: 25, jump: 10, fall: 9, wave: 26, flag: 25 }

const sprites: HogSprites = {
    image: {} as HTMLImageElement,
    animations: Object.fromEntries(
        HOG_ANIMATIONS.map((animation) => [
            animation,
            Array.from({ length: FRAME_COUNTS[animation] }, (_, index) => ({ x: index * 80, y: 0, w: 80, h: 80 })),
        ])
    ) as HogSprites['animations'],
    accessories: {},
}

const world = (reducedMotion: boolean): HogWorld => ({
    ground: 800,
    left: 200,
    right: 1000,
    card: { left: 300, right: 900, top: 100, bottom: 500 } as DOMRect,
    reducedMotion,
})

const stepUntil = (hog: SeasonalHog, done: () => boolean, current: HogWorld): void => {
    for (let i = 0; i < 3000 && !done(); i++) {
        hog.step(current, sprites)
    }
}

const onCard = (): SeasonalHog => {
    const hog = new SeasonalHog(world(false))
    hog.jumpToCard()
    stepUntil(hog, () => hog.state === 'card', world(false))
    return hog
}

describe('SeasonalHog', () => {
    it.each([
        ['standing on the card', (hog: SeasonalHog) => hog.leave()],
        [
            'jumping down from the card',
            (hog: SeasonalHog) => {
                hog.jumpToGround()
                hog.leave()
            },
        ],
        [
            'jumping up to the card',
            (hog: SeasonalHog) => {
                hog.jumpToGround()
                stepUntil(hog, () => hog.state === 'roam', world(false))
                hog.jumpToCard()
                hog.leave()
            },
        ],
    ])('walks away when dismissed while %s', (_, dismiss) => {
        const hog = onCard()
        dismiss(hog)
        stepUntil(hog, () => hog.state === 'away', world(false))
        expect(hog.state).toBe('away')
    })

    it('stays on the page when restored during the farewell wave', () => {
        const hog = new SeasonalHog(world(false))
        hog.leave()
        hog.step(world(false), sprites)
        hog.enter()
        for (let i = 0; i < 200; i++) {
            hog.step(world(false), sprites)
        }
        expect(hog.state).toBe('roam')
    })

    it('leaves at once when dismissed with reduced motion', () => {
        const hog = new SeasonalHog(world(true))
        hog.leave()
        hog.step(world(true), sprites)
        expect(hog.state).toBe('away')
    })

    it('keeps the same sprite frame with reduced motion', () => {
        const hog = new SeasonalHog(world(true))
        hog.wave()
        const drawn: number[] = []
        const context = {
            save: () => undefined,
            restore: () => undefined,
            translate: () => undefined,
            scale: () => undefined,
            drawImage: (_image: unknown, sx: number) => drawn.push(sx),
        } as unknown as CanvasRenderingContext2D
        for (let i = 0; i < 30; i++) {
            hog.step(world(true), sprites)
            hog.draw(context, sprites, [])
        }
        expect(new Set(drawn)).toEqual(new Set([0]))
    })
})

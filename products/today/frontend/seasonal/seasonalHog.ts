import type { HogAnimation, HogSprites } from './seasonalHogSprites'

export const HOG_SIZE = 76

const FEET = HOG_SIZE * 0.9
const WALK_SPEED = 1.1
const LEAVE_SPEED = 1.8
const JUMP_TICKS = 46

export type HogState = 'roam' | 'jump' | 'card' | 'leave' | 'away' | 'enter'

export interface HogWorld {
    ground: number
    left: number
    right: number
    card: DOMRect | null
    reducedMotion: boolean
}

interface HogPoint {
    x: number
    y: number
}

interface HogJump {
    fromX: number
    fromY: number
    tick: number
    target: () => HogPoint
    onLand: () => void
}

export class SeasonalHog {
    x = 0
    y = 0
    state: HogState = 'roam'
    private direction: 1 | -1 = -1
    private animation: HogAnimation = 'idle'
    private frame = 0
    private loop = true
    private onDone: (() => void) | null = null
    private speed = 0
    private timer = 90
    private hovered = false
    private jump: HogJump | null = null
    private world: HogWorld

    constructor(world: HogWorld) {
        this.world = world
        this.x = world.right - 60
        this.y = world.ground
    }

    hit(x: number, y: number): boolean {
        return this.state !== 'away' && Math.abs(x - this.x) < 30 && y > this.y - 66 && y < this.y + 4
    }

    hover(hovered: boolean, pointerX: number): void {
        if (hovered && !this.hovered && this.state === 'roam' && !this.world.reducedMotion) {
            this.speed = 0
            this.timer = 120
            this.direction = pointerX >= this.x ? 1 : -1
            this.wave()
        }
        this.hovered = hovered
    }

    wave(): void {
        this.play('wave', false, () => this.play('idle', true))
    }

    celebrate(): void {
        this.play('flag', false, () => this.play('idle', true))
    }

    jumpToCard(): void {
        if (this.state === 'card' || this.state === 'away' || this.state === 'leave') {
            return
        }
        this.jumpTo(
            () => (this.world.card ? { x: this.world.card.right - 96, y: this.world.card.top + 3 } : this.groundSpot()),
            () => {
                this.state = this.world.card ? 'card' : 'roam'
                this.direction = -1
                this.wave()
            }
        )
    }

    jumpToGround(onGround?: () => void): void {
        if (this.state !== 'card') {
            onGround?.()
            return
        }
        const spot = this.groundSpot()
        this.jumpTo(
            () => ({ x: spot.x, y: this.world.ground }),
            () => {
                this.state = 'roam'
                this.timer = 60
                this.play('idle', true)
                onGround?.()
            }
        )
    }

    leave(): void {
        this.jumpToGround(() => {
            this.play('wave', false, () => {
                this.state = this.world.reducedMotion ? 'away' : 'leave'
                this.direction = -1
                this.play('walk', true)
            })
        })
    }

    enter(): void {
        if (this.state !== 'away' && this.state !== 'leave') {
            return
        }
        this.state = this.world.reducedMotion ? 'roam' : 'enter'
        this.direction = 1
        this.x = this.world.reducedMotion ? this.world.right - 60 : -40
        this.play(this.world.reducedMotion ? 'idle' : 'walk', true)
    }

    step(world: HogWorld, sprites: HogSprites): void {
        this.world = world
        this.advanceFrame(sprites)
        switch (this.state) {
            case 'roam':
                this.roam()
                break
            case 'jump':
                this.stepJump()
                break
            case 'card':
                if (world.card) {
                    this.x = world.card.right - 96
                    this.y = world.card.top + 3
                }
                break
            case 'leave':
                this.x -= LEAVE_SPEED
                this.y = world.ground
                if (this.x < -60) {
                    this.state = 'away'
                }
                break
            case 'enter':
                this.x += LEAVE_SPEED
                this.y = world.ground
                if (this.x > world.left + 80) {
                    this.state = 'roam'
                    this.timer = 40
                    this.play('idle', true)
                }
                break
        }
    }

    draw(context: CanvasRenderingContext2D, sprites: HogSprites, accessories: string[]): void {
        if (this.state === 'away') {
            return
        }
        const frames = sprites.animations[this.animation]
        const frame = frames[Math.min(frames.length - 1, Math.floor(this.frame))]
        context.save()
        context.translate(this.x, this.y - FEET)
        if (this.direction < 0) {
            context.scale(-1, 1)
        }
        const half = HOG_SIZE / 2
        context.drawImage(sprites.image, frame.x, frame.y, frame.w, frame.h, -half, 0, HOG_SIZE, HOG_SIZE)
        for (const name of accessories) {
            const accessory = sprites.accessories[name]
            if (accessory) {
                context.drawImage(
                    sprites.image,
                    accessory.x,
                    accessory.y,
                    accessory.w,
                    accessory.h,
                    -half,
                    0,
                    HOG_SIZE,
                    HOG_SIZE
                )
            }
        }
        context.restore()
    }

    private groundSpot(): HogPoint {
        const x = Math.min(Math.max(this.x - 30, this.world.left + 60), this.world.right - 140)
        return { x, y: this.world.ground }
    }

    private play(animation: HogAnimation, loop: boolean, onDone: (() => void) | null = null): void {
        this.animation = animation
        this.frame = 0
        this.loop = loop
        this.onDone = onDone
    }

    private advanceFrame(sprites: HogSprites): void {
        if (this.state === 'jump') {
            return
        }
        this.frame += this.animation === 'walk' ? 0.32 : 0.42
        const length = sprites.animations[this.animation].length
        if (this.frame >= length) {
            if (this.loop) {
                this.frame %= length
            } else {
                this.frame = length - 1
                const onDone = this.onDone
                this.onDone = null
                if (onDone) {
                    onDone()
                } else {
                    this.play('idle', true)
                }
            }
        }
    }

    private jumpTo(target: () => HogPoint, onLand: () => void): void {
        if (this.world.reducedMotion) {
            const point = target()
            this.x = point.x
            this.y = point.y
            onLand()
            return
        }
        this.state = 'jump'
        this.jump = { fromX: this.x, fromY: this.y, tick: 0, target, onLand }
        this.direction = target().x >= this.x ? 1 : -1
    }

    private stepJump(): void {
        const jump = this.jump
        if (!jump) {
            return
        }
        jump.tick += 1
        const t = Math.min(1, jump.tick / JUMP_TICKS)
        const target = jump.target()
        const lift = 70 + Math.abs(target.y - jump.fromY) * 0.25
        this.x = jump.fromX + (target.x - jump.fromX) * t
        this.y = jump.fromY + (target.y - jump.fromY) * t - 4 * lift * t * (1 - t)
        this.animation = t < 0.85 ? 'jump' : 'fall'
        this.frame = t < 0.85 ? Math.min(6, t * 8) : 6 + (t - 0.85) * 18
        if (t >= 1) {
            this.jump = null
            this.state = 'roam'
            jump.onLand()
        }
    }

    private roam(): void {
        this.y = this.world.ground
        if (this.world.reducedMotion || this.hovered) {
            return
        }
        this.timer -= 1
        if (this.timer <= 0) {
            const roll = Math.random()
            if (roll < 0.55) {
                this.direction = Math.random() < 0.5 ? -1 : 1
                this.speed = WALK_SPEED * this.direction
                this.timer = 70 + Math.random() * 110
                this.play('walk', true)
            } else if (roll < 0.7) {
                this.speed = 0
                this.timer = 140
                this.wave()
            } else {
                this.speed = 0
                this.timer = 90 + Math.random() * 120
                this.play('idle', true)
            }
        }
        if (this.speed) {
            const low = this.world.left + 40
            const high = this.world.right - 40
            this.x += this.speed
            if (this.x < low || this.x > high) {
                this.x = Math.min(Math.max(this.x, low), high)
                this.speed = -this.speed
                this.direction = this.direction === 1 ? -1 : 1
            }
        }
    }
}

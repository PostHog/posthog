// The widget plays this script back, so the shape must match the contract in modules/hedgehog-widget/README.md.
export type Pose = 'idle' | 'walk' | 'jump' | 'wave' | 'action' | 'fall'
export type Facing = 'left' | 'right'

export interface Tick {
    pose: Pose
    frame: number
    x: number
    y: number
    facing: Facing
    bubble?: string
}

export interface Choreography {
    version: 1
    seed: number
    generatedAt: string
    startsAt: string
    keyframeSec: 60
    keyframes: Tick[]
    tickMs: 120
    loopMinutes: 10
    loops: Tick[][]
    reaction: { keyframes: Tick[]; ticks: Tick[] }
}

export const FRAME_COUNTS: Record<Pose, number> = {
    idle: 25,
    walk: 11,
    jump: 10,
    wave: 26,
    action: 16,
    fall: 9,
}

const KEYFRAME_COUNT = 24 * 60
const LOOP_COUNT = 24
const MAX_LOOP_TICKS = 120
const FINISH_IDLE_TICKS = 4
// The renderers clamp the sprite inside the widget, so a centre near the edge pins the hedgehog against it.
const MIN_X = 0.1
const MAX_X = 0.9

const JUMP_AIRBORNE_FRAMES = [4, 5] as const

// Keyframes sit a minute apart, so a pose skips several frames per keyframe to look different on every entry.
// Each stride is coprime with its pool size, so the cycle visits every frame before it repeats.
function framePool(first: number, last: number, stride: number): number[] {
    const size = last - first + 1
    return Array.from({ length: size }, (_, index) => first + ((index * stride) % size))
}

// Wave frames outside 6..18 show the paw down, which reads as idle in a still keyframe.
const KEYFRAME_FRAMES: Record<Pose, readonly number[]> = {
    idle: framePool(0, 24, 4),
    walk: framePool(0, 10, 3),
    jump: JUMP_AIRBORNE_FRAMES,
    wave: framePool(6, 18, 3),
    action: framePool(0, 15, 5),
    fall: [6, 7, 8],
}
const JUMP_LANDED_FRAME = 9

const GREETINGS = ['Hi!', 'Hello!', 'Hey there'] as const
const WORK_LINES = [
    'Shipping',
    'Checking reports',
    'Reading the inbox',
    'Nice PR',
    'Looks good to me',
    'Tests pass',
    'Fixing a bug',
    'New idea',
    'Back to work',
] as const
const STROLL_LINES = ['One more lap', 'Stretching my legs', 'On my way', 'Whee!'] as const
const DANCE_LINES = ['Ta-da!', 'Dance break', 'Shipped it!'] as const
const TRIP_LINES = ['Oops', "I'm okay", 'All good'] as const
const NAP_LINE = 'Zzz'
const THINK_LINE = 'Hmm'

type Random = () => number

// mulberry32: tiny, fast and good enough for choreography. The same seed must give the same day on every device.
function createRandom(seed: number): Random {
    let state = seed >>> 0
    return () => {
        state = (state + 0x6d2b79f5) >>> 0
        let t = state
        t = Math.imul(t ^ (t >>> 15), t | 1)
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
}

function between(random: Random, min: number, max: number): number {
    return min + random() * (max - min)
}

function intBetween(random: Random, min: number, max: number): number {
    return Math.floor(between(random, min, max + 1))
}

function chance(random: Random, probability: number): boolean {
    return random() < probability
}

function pick<T>(random: Random, items: readonly T[]): T {
    return items[Math.floor(random() * items.length)] as T
}

function pickWeighted<T>(random: Random, entries: readonly (readonly [T, number])[]): T {
    const total = entries.reduce((sum, [, weight]) => sum + weight, 0)
    let roll = random() * total
    for (const [item, weight] of entries) {
        roll -= weight
        if (roll < 0) {
            return item
        }
    }
    return (entries[entries.length - 1] as readonly [T, number])[0]
}

function opposite(facing: Facing): Facing {
    return facing === 'left' ? 'right' : 'left'
}

function direction(facing: Facing): number {
    return facing === 'left' ? -1 : 1
}

function roundTo3(value: number): number {
    return Math.round(value * 1000) / 1000
}

function clampX(x: number): number {
    return Math.min(MAX_X, Math.max(MIN_X, x))
}

function makeTick(pose: Pose, frame: number, x: number, y: number, facing: Facing, bubble?: string): Tick {
    const tick: Tick = { pose, frame, x: roundTo3(x), y: roundTo3(y), facing }
    if (bubble) {
        tick.bubble = bubble
    }
    return tick
}

function jumpHeight(progress: number, peak: number): number {
    return 4 * peak * progress * (1 - progress)
}

/** Plans one keyframe per minute for iOS. WidgetKit animates between entries, so each entry is a pose to glide into. */
class KeyframePlanner {
    readonly keyframes: Tick[] = []
    private x: number
    private facing: Facing
    private readonly frameCursors: Record<Pose, number> = { idle: 0, walk: 0, jump: 0, wave: 0, action: 0, fall: 0 }

    constructor(private readonly random: Random) {
        this.x = between(random, 0.3, 0.7)
        this.facing = chance(random, 0.5) ? 'left' : 'right'
    }

    plan(): Tick[] {
        let busy = chance(this.random, 0.5)
        while (this.keyframes.length < KEYFRAME_COUNT) {
            // Alternate short bursts of activity with long quiet stretches, so the day has a rhythm.
            const phaseEnd =
                this.keyframes.length + (busy ? intBetween(this.random, 8, 24) : intBetween(this.random, 10, 40))
            while (this.keyframes.length < phaseEnd) {
                const bit = busy ? pickWeighted(this.random, this.busyBits) : pickWeighted(this.random, this.quietBits)
                bit()
            }
            busy = !busy
        }
        return this.keyframes.slice(0, KEYFRAME_COUNT)
    }

    private readonly busyBits: readonly (readonly [() => void, number])[] = [
        [() => this.stroll(intBetween(this.random, 2, 4)), 3],
        [() => this.strollHopWave(), 2.5],
        [() => this.hop(), 1.5],
        [() => this.dance(), 1.5],
        [() => this.wave(), 1],
        [() => this.trip(), 0.6],
        [() => this.lookAround(), 1],
    ]

    private readonly quietBits: readonly (readonly [() => void, number])[] = [
        [() => this.nap(), 2],
        [() => this.lookAround(), 2],
        [() => this.think(), 1.5],
        [() => this.stroll(intBetween(this.random, 1, 2)), 1],
    ]

    private push(pose: Pose, options: { y?: number; frame?: number; bubble?: string } = {}): void {
        const frame = options.frame ?? this.nextFrame(pose)
        this.keyframes.push(makeTick(pose, frame, this.x, options.y ?? 0, this.facing, options.bubble))
    }

    private nextFrame(pose: Pose): number {
        const pool = KEYFRAME_FRAMES[pose]
        this.frameCursors[pose] = (this.frameCursors[pose] + 1) % pool.length
        return pool[this.frameCursors[pose]] as number
    }

    private step(distance: number): void {
        let target = this.x + direction(this.facing) * distance
        if (target < MIN_X || target > MAX_X) {
            this.facing = opposite(this.facing)
            target = this.x + direction(this.facing) * distance
        }
        this.x = clampX(target)
    }

    private faceTheOpenSide(): void {
        if (this.x < 0.3) {
            this.facing = 'right'
        } else if (this.x > 0.7) {
            this.facing = 'left'
        } else if (chance(this.random, 0.3)) {
            this.facing = opposite(this.facing)
        }
    }

    private stroll(steps: number): void {
        this.faceTheOpenSide()
        for (let index = 0; index < steps; index++) {
            this.step(between(this.random, 0.1, 0.2))
            const bubble = index === 0 && chance(this.random, 0.12) ? pick(this.random, STROLL_LINES) : undefined
            this.push('walk', { bubble })
        }
    }

    private hop(): void {
        this.step(between(this.random, 0.1, 0.16))
        this.push('jump', { y: between(this.random, 0.3, 0.45) })
        this.step(between(this.random, 0.06, 0.1))
        this.push('jump', { frame: JUMP_LANDED_FRAME })
    }

    private strollHopWave(): void {
        this.stroll(intBetween(this.random, 2, 3))
        this.hop()
        this.wave()
    }

    private wave(): void {
        const count = intBetween(this.random, 1, 2)
        for (let index = 0; index < count; index++) {
            const bubble = index === 0 && chance(this.random, 0.5) ? pick(this.random, GREETINGS) : undefined
            this.push('wave', { bubble })
        }
    }

    private dance(): void {
        const count = intBetween(this.random, 2, 4)
        for (let index = 0; index < count; index++) {
            this.x = clampX(this.x + between(this.random, -0.05, 0.05))
            if (chance(this.random, 0.6)) {
                this.facing = opposite(this.facing)
            }
            const bubble = index === count - 1 && chance(this.random, 0.4) ? pick(this.random, DANCE_LINES) : undefined
            this.push('action', { bubble })
        }
    }

    private trip(): void {
        this.stroll(intBetween(this.random, 1, 2))
        this.step(0.06)
        this.push('fall')
        this.push('idle', { bubble: pick(this.random, TRIP_LINES) })
    }

    private lookAround(): void {
        const count = intBetween(this.random, 2, 4)
        for (let index = 0; index < count; index++) {
            if (chance(this.random, 0.7)) {
                this.facing = opposite(this.facing)
            }
            const bubble = index === 0 && chance(this.random, 0.25) ? THINK_LINE : undefined
            this.push('idle', { bubble })
        }
    }

    private think(): void {
        const count = intBetween(this.random, 1, 3)
        const line = pick(this.random, WORK_LINES)
        for (let index = 0; index < count; index++) {
            this.push('idle', { bubble: index === 0 ? line : undefined })
        }
    }

    private nap(): void {
        const count = intBetween(this.random, 6, 20)
        for (let index = 0; index < count; index++) {
            this.push('idle', { bubble: index % 3 === 1 ? NAP_LINE : undefined })
        }
    }
}

/**
 * Builds one Android loop. Ticks play every 120 ms, so each frame advances by one per tick,
 * and a loop must return to where it started because the widget restarts it without a transition.
 */
class LoopBuilder {
    readonly ticks: Tick[] = []
    readonly startX: number
    readonly startFacing: Facing
    private x: number
    private facing: Facing

    constructor(random: Random) {
        this.startX = between(random, 0.3, 0.7)
        this.startFacing = this.startX < 0.5 ? 'right' : 'left'
        this.x = this.startX
        this.facing = this.startFacing
    }

    /** Ticks left before the loop reaches its length limit, after leaving room for `reserve` closing ticks. */
    remaining(reserve = 0): number {
        return MAX_LOOP_TICKS - this.ticks.length - reserve
    }

    hold(pose: Pose, count: number, startFrame = this.continuedFrame(pose)): void {
        for (let index = 0; index < count; index++) {
            this.ticks.push(makeTick(pose, (startFrame + index) % FRAME_COUNTS[pose], this.x, 0, this.facing))
        }
    }

    walk(count: number, speed: number): void {
        const startFrame = this.continuedFrame('walk')
        for (let index = 0; index < count; index++) {
            this.x = clampX(this.x + direction(this.facing) * speed)
            this.ticks.push(makeTick('walk', (startFrame + index) % FRAME_COUNTS.walk, this.x, 0, this.facing))
        }
    }

    private continuedFrame(pose: Pose): number {
        const last = this.ticks[this.ticks.length - 1]
        return last?.pose === pose ? (last.frame + 1) % FRAME_COUNTS[pose] : 0
    }

    /** Walks back to the start x in `count` ticks, whatever drift the routine added on the way out. */
    walkHome(count: number): void {
        const distance = this.startX - this.x
        if (Math.abs(distance) < 0.001) {
            return
        }
        this.facing = distance < 0 ? 'left' : 'right'
        this.walk(count, Math.abs(distance) / count)
        this.x = this.startX
    }

    jump(peak: number, distance = 0): void {
        const frames = FRAME_COUNTS.jump
        const fromX = this.x
        for (let index = 0; index < frames; index++) {
            const progress = index / (frames - 1)
            this.x = clampX(fromX + direction(this.facing) * distance * progress)
            this.ticks.push(makeTick('jump', index, this.x, jumpHeight(progress, peak), this.facing))
        }
    }

    turn(facing: Facing = opposite(this.facing)): void {
        this.facing = facing
    }

    dance(cycles: number): void {
        const frames = FRAME_COUNTS.action
        for (let cycle = 0; cycle < cycles; cycle++) {
            for (let index = 0; index < frames; index++) {
                const sway = 0.03 * Math.sin((2 * Math.PI * index) / frames)
                this.ticks.push(makeTick('action', index, this.startX + sway, 0, this.facing))
            }
            this.turn()
        }
        this.x = this.startX
    }

    fall(drift: number): void {
        const frames = FRAME_COUNTS.fall
        for (let index = 0; index < frames; index++) {
            this.x = clampX(this.x + (direction(this.facing) * drift) / frames)
            this.ticks.push(makeTick('fall', index, this.x, 0, this.facing))
        }
    }

    roomAhead(): number {
        return this.facing === 'right' ? MAX_X - this.x : this.x - MIN_X
    }

    /** Ends facing the starting way with the feet down, so the restart is seamless. */
    finish(): Tick[] {
        this.turn(this.startFacing)
        this.hold('idle', Math.max(1, Math.min(FINISH_IDLE_TICKS, this.remaining())))
        return this.ticks.slice(0, MAX_LOOP_TICKS)
    }
}

type LoopRoutine = (loop: LoopBuilder, random: Random) => void

const LOOP_ROUTINES: readonly LoopRoutine[] = [
    function walkOutAndBack(loop, random) {
        loop.hold('idle', intBetween(random, 3, 6))
        const speed = between(random, 0.008, 0.012)
        const steps = Math.min(intBetween(random, 14, 24), Math.floor(loop.roomAhead() / speed))
        loop.walk(steps, speed)
        loop.turn()
        loop.hold('idle', intBetween(random, 3, 8))
        loop.walkHome(steps)
    },
    function jumpTwice(loop, random) {
        loop.hold('idle', intBetween(random, 3, 6))
        loop.jump(between(random, 0.25, 0.4), Math.min(0.08, loop.roomAhead()))
        loop.hold('idle', intBetween(random, 3, 6))
        loop.turn()
        loop.jump(between(random, 0.3, 0.45))
        loop.walkHome(8)
        loop.hold('idle', 4)
    },
    function danceBreak(loop, random) {
        loop.hold('idle', intBetween(random, 3, 6))
        loop.dance(intBetween(random, 1, 2) * 2)
    },
    function waveHello(loop, random) {
        loop.hold('idle', intBetween(random, 3, 6))
        loop.walk(10, 0.01)
        loop.hold('wave', FRAME_COUNTS.wave)
        loop.hold('idle', intBetween(random, 3, 6))
        loop.walkHome(10)
    },
    function tripAndRecover(loop, random) {
        loop.hold('idle', 4)
        const speed = 0.011
        loop.walk(Math.min(18, Math.floor((loop.roomAhead() - 0.03) / speed)), speed)
        loop.fall(0.03)
        loop.hold('idle', intBetween(random, 6, 10))
        loop.walkHome(22)
    },
    function nap(loop) {
        // finish() appends FINISH_IDLE_TICKS more idle ticks. The total is whole idle cycles, so the animation runs on across the restart.
        loop.hold('idle', FRAME_COUNTS.idle * 2 - FINISH_IDLE_TICKS)
    },
    function hopAlong(loop, random) {
        loop.hold('idle', 4)
        const speed = 0.009
        loop.walk(8, speed)
        loop.jump(between(random, 0.2, 0.3), Math.min(0.08, loop.roomAhead()))
        loop.walk(Math.min(8, Math.floor(loop.roomAhead() / speed)), speed)
        loop.hold('idle', 6)
        loop.walkHome(28)
    },
    function lookAround(loop, random) {
        loop.hold('idle', intBetween(random, 6, 10))
        loop.turn()
        loop.hold('idle', intBetween(random, 6, 10), 8)
        loop.turn()
        loop.hold('wave', FRAME_COUNTS.wave)
        loop.jump(between(random, 0.2, 0.3))
    },
]

function shuffled<T>(random: Random, items: readonly T[]): T[] {
    const result = [...items]
    for (let index = result.length - 1; index > 0; index--) {
        const swap = Math.floor(random() * (index + 1))
        ;[result[index], result[swap]] = [result[swap] as T, result[index] as T]
    }
    return result
}

function planLoops(random: Random): Tick[][] {
    const order: LoopRoutine[] = []
    while (order.length < LOOP_COUNT) {
        const block = shuffled(random, LOOP_ROUTINES)
        // Avoid the same routine twice in a row where two shuffled blocks meet.
        if (block[0] === order[order.length - 1]) {
            block.push(block.shift() as LoopRoutine)
        }
        order.push(...block)
    }
    return order.slice(0, LOOP_COUNT).map((routine) => {
        const loop = new LoopBuilder(random)
        routine(loop, random)
        return loop.finish()
    })
}

// Reactions play wherever the hedgehog stands, so they start at the centre and stay there. A renderer can shift
// every x by its current position minus 0.5.
function planReaction(random: Random): Choreography['reaction'] {
    const greeting = pick(random, GREETINGS)
    const peak = 0.4
    const jumpTicks = Array.from({ length: FRAME_COUNTS.jump }, (_, index) =>
        makeTick('jump', index, 0.5, jumpHeight(index / (FRAME_COUNTS.jump - 1), peak), 'right')
    )
    const waveTicks = Array.from({ length: 20 }, (_, index) => makeTick('wave', index, 0.5, 0, 'right'))
    return {
        keyframes: [
            makeTick('jump', JUMP_AIRBORNE_FRAMES[0], 0.5, peak, 'right'),
            makeTick('wave', 10, 0.5, 0, 'right', greeting),
            makeTick('wave', 16, 0.5, 0, 'right', greeting),
        ],
        ticks: [...jumpTicks, ...waveTicks],
    }
}

/** UTC calendar day as YYYYMMDD, so every device picks the same routine on the same day. */
export function dailySeed(date: Date): number {
    return date.getUTCFullYear() * 10000 + (date.getUTCMonth() + 1) * 100 + date.getUTCDate()
}

export function createChoreography(options: { seed: number; startsAt: Date; generatedAt?: Date }): Choreography {
    const random = createRandom(options.seed)
    return {
        version: 1,
        seed: options.seed,
        generatedAt: (options.generatedAt ?? new Date()).toISOString(),
        startsAt: options.startsAt.toISOString(),
        keyframeSec: 60,
        keyframes: new KeyframePlanner(random).plan(),
        tickMs: 120,
        loopMinutes: 10,
        loops: planLoops(random),
        reaction: planReaction(random),
    }
}

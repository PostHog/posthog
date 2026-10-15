// The widget plays this script back, so the shape must match the contract in modules/hedgehog-widget/README.md.
export type Pose = 'idle' | 'walk' | 'jump' | 'wave' | 'action' | 'fall'
export type Facing = 'left' | 'right'

export const HOGGIES = ['coffee_cup', 'party', 'wizard', 'explorer', 'asleep', 'superhero', 'reading', 'float'] as const
export type Hoggie = (typeof HOGGIES)[number]

const HOGGIE_LINES: Record<Hoggie, string> = {
    coffee_cup: 'Coffee break',
    party: 'Dance break',
    wizard: 'A little magic',
    explorer: 'On an adventure',
    asleep: 'Five more minutes',
    superhero: 'Up, up and away!',
    reading: 'One more chapter',
    float: 'Going with the flow',
}

export interface Tick {
    pose: Pose
    frame: number
    x: number
    y: number
    facing: Facing
    bubble?: string
    turn?: number
    hoggie?: Hoggie
}

export interface Choreography {
    version: 1
    seed: number
    generatedAt: string
    startsAt: string
    keyframeSec: 2
    keyframes: Tick[]
    tickMs: 120
    loopMinutes: 10
    loops: Tick[][]
    reaction: { keyframes: Tick[]; ticks: Tick[] }
    surprises: Choreography['reaction'][]
}

export const FRAME_COUNTS: Record<Pose, number> = {
    idle: 25,
    walk: 11,
    jump: 10,
    wave: 26,
    action: 16,
    fall: 9,
}

// WidgetKit shows a new timeline entry about every 2 seconds at best, so iOS gets one keyframe per 2-second beat
// and glides between them.
const KEYFRAME_SEC = 2
// 30 minutes of beats. The widget wraps around at the end, so the plan walks back to where it started.
const KEYFRAME_COUNT = 900
// Scenes stop this many beats before the end, which leaves room for the longest scene and the walk home.
const FINALE_BEATS = 60
const HOME_STEP = 0.16
const LOOP_COUNT = 16
const MAX_LOOP_TICKS = 120
const FINISH_IDLE_TICKS = 4
// The renderers clamp the sprite inside the widget, so a centre near the edge pins the hedgehog against it.
const MIN_X = 0.1
const MAX_X = 0.9

const JUMP_AIRBORNE_FRAMES = [4, 5] as const

// Consecutive keyframes sit 2 seconds apart, so a pose skips several frames per keyframe to look different on every entry.
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
const FLIP_LINES = ['Whee!', 'Ta-da!', 'Did you see that?', 'One more time'] as const
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

function shuffled<T>(random: Random, items: readonly T[]): T[] {
    const result = [...items]
    for (let index = result.length - 1; index > 0; index--) {
        const swap = Math.floor(random() * (index + 1))
        ;[result[index], result[swap]] = [result[swap] as T, result[index] as T]
    }
    return result
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

function makeTick(
    pose: Pose,
    frame: number,
    x: number,
    y: number,
    facing: Facing,
    extras: { bubble?: string; turn?: number } = {}
): Tick {
    const tick: Tick = { pose, frame, x: roundTo3(x), y: roundTo3(y), facing }
    if (extras.bubble) {
        tick.bubble = extras.bubble
    }
    if (extras.turn) {
        tick.turn = extras.turn
    }
    return tick
}

function jumpHeight(progress: number, peak: number): number {
    return 4 * peak * progress * (1 - progress)
}

type Bit = readonly [() => void, number]

/**
 * Plans one keyframe per 2-second beat for iOS. WidgetKit animates between entries, so each keyframe is a pose to
 * glide into. A scene is a few moves in a row, often a line in a speech bubble, then a short pause.
 */
class KeyframePlanner {
    readonly keyframes: Tick[] = []
    private readonly startX: number
    private x: number
    private facing: Facing
    private readonly frameCursors: Record<Pose, number> = { idle: 0, walk: 0, jump: 0, wave: 0, action: 0, fall: 0 }

    constructor(private readonly random: Random) {
        this.startX = roundTo3(between(random, 0.3, 0.7))
        this.x = this.startX
        this.facing = chance(random, 0.5) ? 'left' : 'right'
    }

    plan(): Tick[] {
        this.push('idle')
        while (this.keyframes.length < KEYFRAME_COUNT - FINALE_BEATS) {
            this.scene()
        }
        // Small moves in place fill the remaining beats, so the walk home ends exactly on the last keyframe.
        // A dance drifts and can add two beats to the walk home, so it only runs while there is room for that.
        for (let slack = this.slack(); slack > 4; slack = this.slack()) {
            if (slack >= 8) {
                pickWeighted(this.random, this.fillers)()
            } else {
                this.lookAround()
            }
        }
        this.rest(this.slack())
        this.walkHome()
        return this.keyframes
    }

    private slack(): number {
        return KEYFRAME_COUNT - this.keyframes.length - this.beatsHome()
    }

    private readonly moves: readonly Bit[] = [
        [() => this.stroll(intBetween(this.random, 2, 4)), 3],
        [() => this.zoom(), 1],
        [() => this.hop(), 1.5],
        [() => this.flip(), 1.5],
        [() => this.flip(true), 0.6],
        [() => this.strollAndFlip(), 1],
        [() => this.dance(), 1],
        [() => this.wave(), 1],
        [() => this.trip(), 0.4],
        [() => this.lookAround(), 0.8],
    ]

    private readonly fillers: readonly Bit[] = [
        [() => this.wave(), 1],
        [() => this.lookAround(), 1],
        [() => this.dance(), 1],
    ]

    private scene(): void {
        const moves = intBetween(this.random, 2, 4)
        for (let index = 0; index < moves; index++) {
            pickWeighted(this.random, this.moves)()
            if (chance(this.random, 0.25)) {
                this.rest(1)
            }
        }
        if (chance(this.random, 0.5)) {
            this.say(pick(this.random, WORK_LINES))
        }
        if (chance(this.random, 0.12)) {
            this.chill()
        } else {
            this.rest(intBetween(this.random, 0, 2))
        }
    }

    private push(pose: Pose, options: { y?: number; frame?: number; bubble?: string; turn?: number } = {}): void {
        const y = options.y ?? 0
        const last = this.keyframes[this.keyframes.length - 1]
        // The widget draws a bubble above the head at floor height, so only a hedgehog standing on the floor talks.
        const grounded = y === 0 && !options.turn && (last?.y ?? 0) === 0
        const bubble = grounded ? options.bubble : undefined
        const frame = options.frame ?? this.nextFrame(pose)
        this.keyframes.push(makeTick(pose, frame, this.x, y, this.facing, { bubble, turn: options.turn }))
    }

    /**
     * Repeats the last keyframe, which the widget merges into one longer entry. The copy drops `turn`, because a
     * repeated half turn would leave the hedgehog upside down.
     */
    private hold(beats: number): void {
        const last = this.keyframes[this.keyframes.length - 1]
        for (let index = 0; index < beats && last; index++) {
            this.keyframes.push(makeTick(last.pose, last.frame, last.x, last.y, last.facing, { bubble: last.bubble }))
        }
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

    /** Moves along the facing direction, or against it for a negative distance, without turning around. */
    private move(distance: number): void {
        this.x = clampX(this.x + direction(this.facing) * distance)
    }

    private room(backwards: boolean): number {
        const towardsRight = (this.facing === 'right') !== backwards
        return towardsRight ? MAX_X - this.x : this.x - MIN_X
    }

    /** Turns around when the move would hit the edge. The widget is 0.8 wide, so the other side always has room. */
    private makeRoom(distance: number, backwards = false): void {
        if (this.room(backwards) < distance) {
            this.facing = opposite(this.facing)
        }
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
            this.step(between(this.random, 0.12, 0.18))
            const bubble = index === 0 && chance(this.random, 0.15) ? pick(this.random, STROLL_LINES) : undefined
            this.push('walk', { bubble })
        }
    }

    private zoom(): void {
        this.faceTheOpenSide()
        const steps = intBetween(this.random, 3, 4)
        for (let index = 0; index < steps; index++) {
            this.step(between(this.random, 0.2, 0.24))
            this.push('walk')
        }
    }

    private hop(): void {
        this.makeRoom(0.24)
        this.move(between(this.random, 0.1, 0.14))
        this.push('jump', { y: between(this.random, 0.3, 0.45) })
        this.move(between(this.random, 0.06, 0.1))
        this.push('jump', { frame: JUMP_LANDED_FRAME })
    }

    /**
     * Two keyframes: up to the top of the jump with half a turn, then down to the floor with the other half.
     * `turn` is clockwise on screen, so a front flip turns the way the hedgehog faces and a backflip the other way.
     */
    private flip(backwards = false): void {
        const travel = between(this.random, 0.08, 0.12)
        this.makeRoom(2 * travel, backwards)
        const turn = 0.5 * direction(this.facing) * (backwards ? -1 : 1)
        const distance = backwards ? -travel : travel
        this.move(distance)
        this.push('jump', { y: between(this.random, 0.7, 0.85), frame: pick(this.random, JUMP_AIRBORNE_FRAMES), turn })
        this.move(distance)
        this.push('jump', { frame: JUMP_LANDED_FRAME, turn })
        if (chance(this.random, 0.5)) {
            this.say(pick(this.random, FLIP_LINES), 1)
        }
    }

    private strollAndFlip(): void {
        this.stroll(2)
        this.flip()
    }

    private wave(): void {
        const count = intBetween(this.random, 1, 2)
        for (let index = 0; index < count; index++) {
            const bubble = index === 0 && chance(this.random, 0.5) ? pick(this.random, GREETINGS) : undefined
            this.push('wave', { bubble })
        }
    }

    private dance(): void {
        const count = intBetween(this.random, 3, 5)
        const hopAt = chance(this.random, 0.4) ? intBetween(this.random, 1, count - 2) : -1
        for (let index = 0; index < count; index++) {
            this.x = clampX(this.x + between(this.random, -0.05, 0.05))
            if (chance(this.random, 0.6)) {
                this.facing = opposite(this.facing)
            }
            if (index === hopAt) {
                this.push('jump', { y: between(this.random, 0.15, 0.22) })
                continue
            }
            const bubble = index === count - 1 && chance(this.random, 0.4) ? pick(this.random, DANCE_LINES) : undefined
            this.push('action', { bubble })
        }
    }

    private trip(): void {
        this.stroll(intBetween(this.random, 1, 2))
        this.step(0.05)
        this.push('fall')
        this.hold(1)
        this.push('idle', { bubble: pick(this.random, TRIP_LINES) })
        this.hold(1)
    }

    private lookAround(): void {
        const count = intBetween(this.random, 2, 3)
        for (let index = 0; index < count; index++) {
            if (chance(this.random, 0.7)) {
                this.facing = opposite(this.facing)
            }
            const bubble = index === 0 && chance(this.random, 0.25) ? THINK_LINE : undefined
            this.push('idle', { bubble })
        }
    }

    private say(line: string, beats = 2): void {
        this.push(chance(this.random, 0.3) ? 'wave' : 'idle', { bubble: line })
        this.hold(beats - 1)
    }

    private rest(beats: number): void {
        if (beats <= 0) {
            return
        }
        this.push('idle')
        this.hold(beats - 1)
    }

    /** A longer quiet moment: a nap, or a thought and a look around. */
    private chill(): void {
        if (chance(this.random, 0.5)) {
            const count = intBetween(this.random, 4, 8)
            for (let index = 0; index < count; index++) {
                this.push('idle', { bubble: index % 3 === 1 ? NAP_LINE : undefined })
            }
            return
        }
        this.say(pick(this.random, WORK_LINES))
        this.lookAround()
    }

    private beatsHome(): number {
        return Math.ceil(Math.abs(this.startX - this.x) / HOME_STEP - 0.001)
    }

    private walkHome(): void {
        const beats = this.beatsHome()
        if (beats === 0) {
            return
        }
        const distance = this.startX - this.x
        this.facing = distance < 0 ? 'left' : 'right'
        for (let index = 1; index <= beats; index++) {
            this.x = index === beats ? this.startX : this.x + distance / beats
            this.push('walk')
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

    /**
     * Runs a routine and keeps it only when it fits with room left for the closing ticks. Every routine ends back
     * at the start x, so routines chain without a jump.
     */
    append(routine: LoopRoutine, random: Random): boolean {
        const length = this.ticks.length
        const facing = this.facing
        routine(this, random)
        if (this.ticks.length <= MAX_LOOP_TICKS - FINISH_IDLE_TICKS) {
            return true
        }
        this.ticks.length = length
        this.x = this.startX
        this.facing = facing
        return false
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
        this.hold('idle', Math.max(1, Math.min(FINISH_IDLE_TICKS, MAX_LOOP_TICKS - this.ticks.length)))
        return this.ticks.slice(0, MAX_LOOP_TICKS)
    }
}

type LoopRoutine = (loop: LoopBuilder, random: Random) => void

const LOOP_ROUTINES: readonly LoopRoutine[] = [
    function walkOutAndBack(loop, random) {
        loop.hold('idle', intBetween(random, 2, 4))
        const speed = between(random, 0.008, 0.012)
        const steps = Math.min(intBetween(random, 14, 24), Math.floor(loop.roomAhead() / speed))
        loop.walk(steps, speed)
        loop.turn()
        loop.hold('idle', intBetween(random, 2, 5))
        loop.walkHome(steps)
    },
    function jumpTwice(loop, random) {
        loop.hold('idle', intBetween(random, 2, 4))
        loop.jump(between(random, 0.25, 0.4), Math.min(0.08, loop.roomAhead()))
        loop.hold('idle', intBetween(random, 2, 4))
        loop.turn()
        loop.jump(between(random, 0.3, 0.45))
        loop.walkHome(8)
    },
    function danceBreak(loop, random) {
        loop.hold('idle', intBetween(random, 2, 4))
        loop.dance(intBetween(random, 1, 2) * 2)
    },
    function waveHello(loop, random) {
        loop.hold('idle', intBetween(random, 2, 4))
        loop.walk(10, 0.01)
        loop.hold('wave', FRAME_COUNTS.wave)
        loop.walkHome(10)
    },
    function tripAndRecover(loop, random) {
        loop.hold('idle', 2)
        const speed = 0.011
        loop.walk(Math.min(18, Math.floor((loop.roomAhead() - 0.03) / speed)), speed)
        loop.fall(0.03)
        loop.hold('idle', intBetween(random, 4, 6))
        loop.walkHome(22)
    },
    function hopAlong(loop, random) {
        loop.hold('idle', 2)
        const speed = 0.009
        loop.walk(8, speed)
        loop.jump(between(random, 0.2, 0.3), Math.min(0.08, loop.roomAhead()))
        loop.walk(Math.min(8, Math.floor(loop.roomAhead() / speed)), speed)
        loop.hold('idle', 3)
        loop.walkHome(28)
    },
    function lookAround(loop, random) {
        loop.hold('idle', intBetween(random, 4, 6))
        loop.turn()
        loop.hold('idle', intBetween(random, 4, 6), 8)
        loop.turn()
        loop.hold('wave', FRAME_COUNTS.wave)
        loop.jump(between(random, 0.2, 0.3))
    },
]

function illustratedLoop(hoggie: Hoggie, anchor: Tick, count = 80): Tick[] {
    return Array.from({ length: count }, (_, index) => {
        const progress = index / (count - 1)
        const travelling = hoggie === 'explorer' || hoggie === 'superhero' || hoggie === 'float'
        const sway = hoggie === 'party' ? 0.035 * Math.sin(progress * Math.PI * 6) : 0
        const travel = travelling ? 0.16 * Math.sin(progress * Math.PI * 2) : sway
        const hop = hoggie === 'wizard' || hoggie === 'superhero' || hoggie === 'party'
        return {
            ...makeTick(
                travelling ? 'walk' : 'idle',
                0,
                anchor.x + travel,
                hop ? 0.12 * Math.sin(progress * Math.PI * 2) ** 2 : 0,
                travelling && index >= count / 2 ? opposite(anchor.facing) : anchor.facing
            ),
            hoggie,
            ...(index === 0 ? { bubble: HOGGIE_LINES[hoggie] } : {}),
        }
    }).map((tick, index) => (index === count - 1 ? { ...tick, facing: anchor.facing, y: 0 } : tick))
}

function planLoops(random: Random): Tick[][] {
    const queue: LoopRoutine[] = []
    const nextRoutine = (): LoopRoutine => {
        if (queue.length === 0) {
            queue.push(...shuffled(random, LOOP_ROUTINES))
        }
        return queue.shift() as LoopRoutine
    }
    return Array.from({ length: LOOP_COUNT }, () => {
        const loop = new LoopBuilder(random)
        // Chain routines until the next one does not fit, so the hedgehog stays busy for the whole loop.
        let fits = true
        while (fits) {
            fits = loop.append(nextRoutine(), random)
        }
        return loop.finish()
    })
}

function planSurprises(random: Random): Choreography['reaction'][] {
    return shuffled(random, HOGGIES).map((hoggie) => ({
        keyframes: [
            { ...makeTick('wave', 10, 0.5, 0, 'right', { bubble: HOGGIE_LINES[hoggie] }), hoggie },
            { ...makeTick('jump', 4, 0.5, hoggie === 'asleep' || hoggie === 'reading' ? 0 : 0.2, 'right'), hoggie },
            { ...makeTick('idle', 0, 0.5, 0, 'right', { bubble: HOGGIE_LINES[hoggie] }), hoggie },
            { ...makeTick('idle', 0, 0.5, 0, 'right', { bubble: HOGGIE_LINES[hoggie] }), hoggie },
        ],
        ticks: illustratedLoop(hoggie, makeTick('idle', 0, 0.5, 0, 'right'), 32).map((tick) => ({
            ...tick,
            x: 0.5,
            facing: 'right',
        })),
    }))
}

// Reactions play wherever the hedgehog stands, so they start at the centre and stay there. A renderer can shift
// every x by its current position minus 0.5. They are authored facing right, so a renderer that turns them to face
// left also negates `turn`.
function planReaction(random: Random): Choreography['reaction'] {
    const greeting = pick(random, GREETINGS)
    const peak = 0.4
    const jumpTicks = Array.from({ length: FRAME_COUNTS.jump }, (_, index) =>
        makeTick('jump', index, 0.5, jumpHeight(index / (FRAME_COUNTS.jump - 1), peak), 'right')
    )
    const waveTicks = Array.from({ length: 20 }, (_, index) => makeTick('wave', index, 0.5, 0, 'right'))
    return {
        keyframes: [
            makeTick('jump', JUMP_AIRBORNE_FRAMES[0], 0.5, 0.8, 'right', { turn: 0.5 }),
            makeTick('jump', JUMP_LANDED_FRAME, 0.5, 0, 'right', { turn: 0.5 }),
            makeTick('wave', 10, 0.5, 0, 'right', { bubble: greeting }),
            makeTick('wave', 16, 0.5, 0, 'right', { bubble: greeting }),
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
        keyframeSec: KEYFRAME_SEC,
        keyframes: new KeyframePlanner(random).plan(),
        tickMs: 120,
        loopMinutes: 10,
        loops: planLoops(random),
        reaction: planReaction(random),
        surprises: planSurprises(random),
    }
}

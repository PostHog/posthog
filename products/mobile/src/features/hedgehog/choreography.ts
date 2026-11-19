import {
    type ActionWeights,
    GROUND_JUMP_APEX,
    HEDGEHOG_MODE_ACTIONS,
    HEDGEHOG_PHYSICS,
    HedgehogSimulation,
    type Random,
    type SimPose,
} from './physics'

// The widget plays this script back, so the shape must match the contract in modules/hedgehog-widget/README.md.
export type Pose = 'idle' | 'walk' | 'jump' | 'wave' | 'action' | 'fall'
export type Facing = 'left' | 'right'

export const HOGGIES = ['coffee_cup', 'party', 'wizard', 'explorer', 'superhero', 'reading', 'float'] as const
export type Hoggie = (typeof HOGGIES)[number]

const HOGGIE_LINES: Record<Hoggie, string> = {
    coffee_cup: 'Coffee break',
    party: 'Dance break',
    wizard: 'A little magic',
    explorer: 'On an adventure',
    superhero: 'Up, up and away!',
    reading: 'One more chapter',
    float: 'Going with the flow',
}

export interface Flight {
    airtime: number
    apex: number
}

export type Motion =
    | { kind: 'idle' }
    | { kind: 'walk' }
    | ({ kind: 'jump'; bounces: Flight[]; turns?: number } & Flight)

export interface Tick {
    pose: Pose
    frame: number
    x: number
    y: number
    facing: Facing
    bubble?: string
    turn?: number
    hoggie?: Hoggie
    motion?: Motion
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

// WidgetKit shows a new timeline entry about every 2 seconds at best, so iOS gets one keyframe per 2-second beat,
// and the AI picks one action per beat.
const KEYFRAME_SEC = 2
// 30 minutes of beats. The widget wraps around at the end, so the last beats walk back to where the first started.
const KEYFRAME_COUNT = 900
// Two beats of walking cross the whole travel width.
const HOME_BEATS = 2
// iOS can rotate the sprite, so it gets a rare flip on top of hedgehog-mode's actions.
const KEYFRAME_ACTIONS: ActionWeights = { ...HEDGEHOG_MODE_ACTIONS, flip: 0.3 }
// A slide after a walk shows the walk sprite for about 5 steps and moves about 0.025 sprites. More than either is a walk.
const WALK_MIN_STEPS = 15
const WALK_MIN_DISTANCE = 0.05

const LOOP_COUNT = 16
const LOOP_CADENCE_SEC = 1
const TICK_SEC = 0.12
const MAX_LOOP_TICKS = 120
const FINISH_IDLE_TICKS = 4
// The longest single action (a wave and its rest) and the longest settle after it (a jump from a bounce).
const LOOP_ACTION_SEC = 2
const LOOP_SETTLE_SEC = 2

// A medium iOS widget or a 4x2 Android widget is about 2.8 sprites wide, and renderers scale x 0..1 into their own
// travel envelope. The widget is shorter than a jump, so a jump from the ground peaks at the top of the available rise.
const TRAVEL_WIDTH = 2.8

const GREETINGS = ['Hi!', 'Hello!', 'Hey there'] as const

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

function pick<T>(random: Random, items: readonly T[]): T {
    return items[Math.floor(random() * items.length)] as T
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

function roundTo3(value: number): number {
    return Math.round(value * 1000) / 1000
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

function normalizedX(x: number): number {
    return Math.min(1, Math.max(0, x / TRAVEL_WIDTH))
}

function normalizedY(y: number): number {
    return Math.min(1, Math.max(0, y / GROUND_JUMP_APEX))
}

function createSimulation(random: Random, cadenceSec: number, actions: ActionWeights): HedgehogSimulation {
    const x = between(random, 0.3, 0.7) * TRAVEL_WIDTH
    return new HedgehogSimulation({
        random,
        cadenceSec,
        width: TRAVEL_WIDTH,
        start: { x, facing: random() < 0.5 ? 'left' : 'right' },
        actions,
        frameCounts: FRAME_COUNTS,
    })
}

/** The jump that took off in this beat, with every bounce that followed it. */
function jumpMotion(simulation: HedgehogSimulation, fromEvent: number): Motion | null {
    const events = simulation.events.slice(fromEvent)
    const takeoff = events.findIndex((event) => event.type === 'takeoff' && event.cause === 'jump')
    const start = events[takeoff]
    if (takeoff < 0 || start?.type !== 'takeoff') {
        return null
    }
    const flights: Flight[] = []
    for (const event of events.slice(takeoff + 1)) {
        if (event.type !== 'landing') {
            continue
        }
        flights.push({
            airtime: roundTo3(event.airtimeSteps / HEDGEHOG_PHYSICS.stepHz),
            apex: roundTo3(normalizedY(event.apex)),
        })
        if (!event.bounced) {
            break
        }
    }
    const [main, ...bounces] = flights
    if (!main) {
        return null
    }
    return { kind: 'jump', ...main, bounces, ...(start.turns ? { turns: start.turns } : {}) }
}

/**
 * Plans one keyframe per 2-second beat for iOS. Each keyframe is where the beat ends, always on the ground, and its
 * `motion` says how the hedgehog got there. The pose is the sprite the beat shows most: `fall` for a jump (the
 * in-game hedgehog falls whenever it is airborne), `wave` for a wave, otherwise the walk or idle sprite.
 */
function planKeyframes(random: Random): Tick[] {
    const simulation = createSimulation(random, KEYFRAME_SEC, KEYFRAME_ACTIONS)
    const homeX = simulation.state.x
    const beatSteps = KEYFRAME_SEC * HEDGEHOG_PHYSICS.stepHz
    const keyframes: Tick[] = []
    for (let beat = 0; beat < KEYFRAME_COUNT; beat++) {
        if (beat === KEYFRAME_COUNT - HOME_BEATS) {
            simulation.stopAI()
            simulation.walkTo(homeX)
        }
        const fromX = simulation.state.x
        const fromEvent = simulation.events.length
        const samples: { pose: SimPose; frame: number }[] = []
        for (let step = 0; step < beatSteps; step++) {
            simulation.advance()
            const { pose, frame } = simulation.state
            samples.push({ pose, frame })
        }
        const end = simulation.state
        const distance = end.x - fromX
        const walkSteps = samples.filter((sample) => sample.pose === 'walk').length
        const motion: Motion =
            jumpMotion(simulation, fromEvent) ??
            (walkSteps >= WALK_MIN_STEPS || Math.abs(distance) >= WALK_MIN_DISTANCE
                ? { kind: 'walk' }
                : { kind: 'idle' })
        let pose: SimPose = 'idle'
        if (motion.kind === 'jump') {
            pose = 'fall'
        } else if (motion.kind === 'walk') {
            pose = 'walk'
        } else if (samples.some((sample) => sample.pose === 'wave')) {
            pose = 'wave'
        }
        const shown = samples.filter((sample) => sample.pose === pose)
        const frame = shown[Math.floor(shown.length / 2)]?.frame ?? 0
        // An edge turns the hedgehog around mid-beat. The glide only shows where it ends up, so it faces that way.
        let facing = end.facing
        if (motion.kind === 'walk' && Math.abs(distance) >= WALK_MIN_DISTANCE) {
            facing = distance < 0 ? 'left' : 'right'
        }
        keyframes.push({ ...makeTick(pose, frame, normalizedX(end.x), normalizedY(end.y), facing), motion })
    }
    return keyframes
}

/**
 * Plans one Android loop: the AI runs at hedgehog-mode's 1-second cadence while there is room left to settle, walk
 * home and stand still. The widget restarts a loop without a transition, so it ends where and how it started.
 */
function planLoop(random: Random): Tick[] {
    const simulation = createSimulation(random, LOOP_CADENCE_SEC, HEDGEHOG_MODE_ACTIONS)
    const home = simulation.state
    const ticks: Tick[] = []
    const sample = (): void => {
        const { pose, frame, x, y, facing } = simulation.state
        ticks.push(makeTick(pose, frame, normalizedX(x), normalizedY(y), facing))
    }
    const advanceToNextTick = (): void => {
        const next = Math.round(ticks.length * TICK_SEC * HEDGEHOG_PHYSICS.stepHz)
        while (simulation.step < next) {
            simulation.advance()
        }
        sample()
    }
    const ticksFor = (seconds: number): number => Math.ceil(seconds / TICK_SEC)
    const roomForAnotherAction = (): boolean => {
        const homeSec =
            (Math.abs(simulation.state.x - home.x) + LOOP_ACTION_SEC * HEDGEHOG_PHYSICS.walkSpeed) /
            (HEDGEHOG_PHYSICS.walkSpeed * (1 - HEDGEHOG_PHYSICS.frictionAir))
        const needed = ticksFor(LOOP_ACTION_SEC + LOOP_SETTLE_SEC + homeSec) + FINISH_IDLE_TICKS + 1
        return ticks.length + needed <= MAX_LOOP_TICKS
    }

    sample()
    while (simulation.aiEnabled) {
        if (simulation.decisionDue && !roomForAnotherAction()) {
            simulation.stopAI()
            break
        }
        simulation.advance()
        if (simulation.step === Math.round(ticks.length * TICK_SEC * HEDGEHOG_PHYSICS.stepHz)) {
            sample()
        }
    }
    while (!simulation.settled) {
        advanceToNextTick()
    }
    simulation.walkTo(home.x)
    while (!simulation.arrived || !simulation.settled) {
        advanceToNextTick()
    }
    simulation.face(home.facing)
    for (let index = 0; index < FINISH_IDLE_TICKS; index++) {
        advanceToNextTick()
    }
    return ticks
}

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

function planSurprises(random: Random): Choreography['reaction'][] {
    return shuffled(random, HOGGIES).map((hoggie) => ({
        keyframes: [
            { ...makeTick('wave', 10, 0.5, 0, 'right', { bubble: HOGGIE_LINES[hoggie] }), hoggie },
            { ...makeTick('jump', 4, 0.5, hoggie === 'reading' ? 0 : 0.2, 'right'), hoggie },
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
            makeTick('jump', 4, 0.5, 0.8, 'right', { turn: 0.5 }),
            makeTick('jump', 9, 0.5, 0, 'right', { turn: 0.5 }),
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
        keyframes: planKeyframes(random),
        tickMs: 120,
        loopMinutes: 10,
        loops: Array.from({ length: LOOP_COUNT }, () => planLoop(random)),
        reaction: planReaction(random),
        surprises: planSurprises(random),
    }
}

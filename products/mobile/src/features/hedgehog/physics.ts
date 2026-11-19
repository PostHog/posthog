import type { Facing, Pose } from './choreography'

/**
 * A fixed-step port of the hedgehog actor from `@posthog/hedgehog-mode` (Matter.js body + `HedgehogActorAI`), so the
 * widget moves like the hedgehog people know from the web app. Distances are in sprite heights (one 80 px sprite)
 * and speeds in sprite heights per second. Matter.js works in px per 60 Hz step, so a Matter velocity of 1 is 0.75 here.
 */

export type Random = () => number

/** The in-game hedgehog never plays `jump` (spawn only) or `action` on its own. */
export type SimPose = Extract<Pose, 'idle' | 'walk' | 'wave' | 'fall'>

/** `flip` is not in hedgehog-mode. It is a jump that the renderer turns over once. */
export type HedgehogAction = 'walk' | 'wait' | 'jump' | 'wave' | 'flip'

export type ActionWeights = Readonly<Partial<Record<HedgehogAction, number>>>

/** The weights from hedgehog-mode's `HedgehogActorAI.actions`. */
export const HEDGEHOG_MODE_ACTIONS: ActionWeights = { walk: 10, wait: 3, jump: 1, wave: 1 }

const STEP_HZ = 60
const SPRITE_PX = 80
const PX_PER_STEP = STEP_HZ / SPRITE_PX

export const HEDGEHOG_PHYSICS = {
    stepHz: STEP_HZ,
    // Matter adds gravity.y * gravity.scale * delta^2 px per step to the velocity: 2 * 0.001 * (1000 / 60)^2.
    gravity: ((2 * 0.001 * (1000 / STEP_HZ) ** 2) / SPRITE_PX) * STEP_HZ ** 2,
    jumpSpeed: 15 * PX_PER_STEP,
    walkSpeed: 1 * PX_PER_STEP,
    frictionAir: 0.01,
    restitution: 0.5,
    // A rebound slower than this settles. Matter keeps bouncing a little longer, but those hops are under 3 px high.
    restingSpeed: 2 * PX_PER_STEP,
    // Approximates Matter's friction impulse between the hedgehog and the ground: a walk stops within about 5 steps.
    groundFriction: 0.2 * PX_PER_STEP,
    walkThreshold: 0.1 * PX_PER_STEP,
    maxJumps: 2,
    // PIXI plays the sheets at animationSpeed 0.5 on a 60 fps ticker.
    spriteFps: 30,
    waveRestSec: 1,
} as const

/** Height of a jump from the ground. frictionAir keeps it below the drag-free 2.53. */
export const GROUND_JUMP_APEX = ((): number => {
    let vy: number = HEDGEHOG_PHYSICS.jumpSpeed
    let apex = 0
    for (;;) {
        vy = vy * (1 - HEDGEHOG_PHYSICS.frictionAir) - HEDGEHOG_PHYSICS.gravity / STEP_HZ
        if (vy <= 0) {
            return apex
        }
        apex += vy / STEP_HZ
    }
})()

export type PhysicsEvent =
    | { type: 'action'; step: number; action: HedgehogAction }
    /** `turns` counts whole flips, clockwise on screen, so a forward flip facing left is negative. */
    | { type: 'takeoff'; step: number; cause: 'jump' | 'bounce'; speed: number; turns: number }
    /** Ends the flight that started at the last takeoff. `bounced` means a bounce takeoff follows on the same step. */
    | { type: 'landing'; step: number; impactSpeed: number; apex: number; airtimeSteps: number; bounced: boolean }

export interface HedgehogState {
    x: number
    y: number
    vx: number
    vy: number
    facing: Facing
    pose: SimPose
    frame: number
    grounded: boolean
}

export interface SimulationOptions {
    random: Random
    /** Seconds between AI decisions. hedgehog-mode re-runs its AI every second. */
    cadenceSec: number
    /** Travel width in sprite heights. The hedgehog turns around at both edges. */
    width: number
    start: { x: number; facing: Facing }
    actions: ActionWeights
    frameCounts: Readonly<Record<SimPose, number>>
}

function opposite(facing: Facing): Facing {
    return facing === 'left' ? 'right' : 'left'
}

function sign(facing: Facing): number {
    return facing === 'left' ? -1 : 1
}

export class HedgehogSimulation {
    readonly events: PhysicsEvent[] = []
    private stepIndex = 0
    private x: number
    private y = 0
    private vx = 0
    private vy = 0
    private facing: Facing
    private walkSpeed = 0
    private jumps = 0
    private grounded = true
    private pose: SimPose = 'idle'
    private poseSteps = 0
    private flightStart = 0
    private flightApex = 0
    private nextDecision: number | null = 0
    private walkTarget: number | null = null
    private readonly cadenceSteps: number
    private readonly waveSteps: number
    private readonly actions: readonly (readonly [HedgehogAction, number])[]

    constructor(private readonly options: SimulationOptions) {
        this.x = options.start.x
        this.facing = options.start.facing
        this.cadenceSteps = Math.round(options.cadenceSec * STEP_HZ)
        this.waveSteps = Math.ceil((options.frameCounts.wave * STEP_HZ) / HEDGEHOG_PHYSICS.spriteFps)
        this.actions = (Object.entries(options.actions) as [HedgehogAction, number][]).filter(
            ([, weight]) => weight > 0
        )
    }

    get step(): number {
        return this.stepIndex
    }

    get state(): HedgehogState {
        const frames = this.options.frameCounts[this.pose]
        const played = Math.floor((this.poseSteps * HEDGEHOG_PHYSICS.spriteFps) / STEP_HZ)
        return {
            x: this.x,
            y: this.y,
            vx: this.vx,
            vy: this.vy,
            facing: this.facing,
            pose: this.pose,
            frame: this.pose === 'wave' ? Math.min(played, frames - 1) : played % frames,
            grounded: this.grounded,
        }
    }

    /** The AI picks its next action at the start of the next step. */
    get decisionDue(): boolean {
        return this.nextDecision === this.stepIndex
    }

    get aiEnabled(): boolean {
        return this.nextDecision !== null
    }

    get settled(): boolean {
        return this.grounded && this.vx === 0
    }

    get arrived(): boolean {
        return this.walkTarget === null
    }

    stopAI(): void {
        this.nextDecision = null
        this.walkSpeed = 0
    }

    /** Walks to `x` at the AI's walking speed and stops there. The AI must be off. */
    walkTo(x: number): void {
        if (Math.abs(x - this.x) < 1e-9) {
            return
        }
        this.walkTarget = x
        this.facing = x < this.x ? 'left' : 'right'
        this.walkSpeed = sign(this.facing) * HEDGEHOG_PHYSICS.walkSpeed
    }

    face(facing: Facing): void {
        this.facing = facing
    }

    /** Runs one action now, like `HedgehogActorAI.run(action)`. */
    perform(action: HedgehogAction): void {
        this.events.push({ type: 'action', step: this.stepIndex, action })
        this.walkSpeed = 0
        switch (action) {
            case 'walk':
                this.facing = this.options.random() < 0.5 ? 'left' : 'right'
                this.walkSpeed = sign(this.facing) * HEDGEHOG_PHYSICS.walkSpeed
                break
            case 'jump':
                this.jump(0)
                break
            case 'flip':
                this.jump(sign(this.facing))
                break
            case 'wave':
                // In the air the sprite rule shows `fall` at once and the wave never plays.
                if (this.grounded) {
                    // hedgehog-mode keeps sliding after a walk, and the slide replaces the wave with `walk`.
                    // Planting the feet lets every wave play, which matters more on a widget that rarely waves.
                    this.vx = 0
                    this.setPose('wave')
                }
                break
            case 'wait':
                break
        }
    }

    run(steps: number): void {
        for (let index = 0; index < steps; index++) {
            this.advance()
        }
    }

    /** One 60 Hz step, in the order hedgehog-mode runs it: AI timer, Matter engine update, then the actor update. */
    advance(): void {
        if (this.decisionDue) {
            this.decide()
        }
        this.integrate()
        this.collideWithGround()
        this.keepInsideWidth()
        this.stopAtWalkTarget()
        if (this.walkSpeed !== 0) {
            this.vx = this.walkSpeed
        }
        this.updateSprite()
        this.stepIndex++
    }

    private decide(): void {
        const action = this.pickAction()
        this.perform(action)
        // `run()` re-arms a 1 s timer after every action, which replaces the random pauses inside `walk` and `wait`.
        // A wave re-arms it again when its one-shot animation ends. Decisions stay on the cadence grid so that
        // every iOS beat holds exactly one action.
        const hold = this.pose === 'wave' ? this.waveSteps + HEDGEHOG_PHYSICS.waveRestSec * STEP_HZ : this.cadenceSteps
        this.nextDecision = this.stepIndex + Math.ceil(hold / this.cadenceSteps) * this.cadenceSteps
    }

    private pickAction(): HedgehogAction {
        const total = this.actions.reduce((sum, [, weight]) => sum + weight, 0)
        let roll = this.options.random() * total
        for (const [action, weight] of this.actions) {
            roll -= weight
            if (roll < 0) {
                return action
            }
        }
        return (this.actions[this.actions.length - 1] as readonly [HedgehogAction, number])[0]
    }

    private jump(turns: number): void {
        if (this.jumps + 1 > HEDGEHOG_PHYSICS.maxJumps) {
            return
        }
        this.vx = 0
        this.vy = HEDGEHOG_PHYSICS.jumpSpeed
        this.jumps++
        this.takeOff('jump', turns)
    }

    private takeOff(cause: 'jump' | 'bounce', turns: number): void {
        this.grounded = false
        this.flightStart = this.stepIndex
        this.flightApex = this.y
        this.events.push({ type: 'takeoff', step: this.stepIndex, cause, speed: this.vy, turns })
    }

    private integrate(): void {
        const dt = 1 / STEP_HZ
        const drag = 1 - HEDGEHOG_PHYSICS.frictionAir
        this.vx *= drag
        if (this.grounded) {
            if (this.walkSpeed === 0) {
                const slowdown = Math.min(Math.abs(this.vx), HEDGEHOG_PHYSICS.groundFriction)
                this.vx -= Math.sign(this.vx) * slowdown
            }
        } else {
            this.vy = this.vy * drag - HEDGEHOG_PHYSICS.gravity * dt
        }
        this.x += this.vx * dt
        this.y += this.vy * dt
        if (!this.grounded) {
            this.flightApex = Math.max(this.flightApex, this.y)
        }
    }

    private collideWithGround(): void {
        if (this.grounded || this.y > 0) {
            return
        }
        const impactSpeed = -this.vy
        const rebound = impactSpeed * HEDGEHOG_PHYSICS.restitution
        const bounced = rebound >= HEDGEHOG_PHYSICS.restingSpeed
        this.y = 0
        this.jumps = 0
        this.events.push({
            type: 'landing',
            step: this.stepIndex,
            impactSpeed,
            apex: this.flightApex,
            airtimeSteps: this.stepIndex - this.flightStart,
            bounced,
        })
        if (bounced) {
            this.vy = rebound
            this.takeOff('bounce', 0)
        } else {
            this.vy = 0
            this.grounded = true
        }
    }

    /** hedgehog-mode wraps to the other side of the screen. On a widget that reads as a teleport, so it turns around. */
    private keepInsideWidth(): void {
        const width = this.options.width
        if (this.x >= 0 && this.x <= width) {
            return
        }
        this.x = Math.min(width, Math.max(0, this.x))
        this.facing = opposite(this.facing)
        this.walkSpeed = -this.walkSpeed
        this.vx = -this.vx
    }

    private stopAtWalkTarget(): void {
        if (this.walkTarget === null) {
            return
        }
        const remaining = (this.walkTarget - this.x) * sign(this.facing)
        if (remaining > 0) {
            return
        }
        this.x = this.walkTarget
        this.vx = 0
        this.walkSpeed = 0
        this.walkTarget = null
    }

    /** `HedgehogActor.update`: airborne shows `fall`, a noticeable slide shows `walk`, and those settle into `idle`. */
    private updateSprite(): void {
        let next = this.pose
        if (!this.grounded) {
            next = 'fall'
        } else if (Math.abs(this.vx) > HEDGEHOG_PHYSICS.walkThreshold) {
            next = 'walk'
        } else if (this.pose === 'fall' || this.pose === 'walk') {
            next = 'idle'
        } else if (this.pose === 'wave' && this.poseSteps + 1 >= this.waveSteps) {
            // hedgehog-mode freezes on the last wave frame, which shows the paw down like `idle`.
            next = 'idle'
        }
        if (next === this.pose) {
            this.poseSteps++
        } else {
            this.setPose(next)
        }
    }

    private setPose(pose: SimPose): void {
        this.pose = pose
        this.poseSteps = 0
    }
}

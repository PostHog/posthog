export interface ObservationFrameProgress {
    phase?: 'setup' | 'capture' | 'upload'
    frame: number
    estimatedTotalFrames: number
}

export interface ObservationRasterizerProgress {
    frame_progress: ObservationFrameProgress | null
}

/** Live progress payload from the `observation-progress` SSE event (mirrors backend ObservationProgress). */
export interface ObservationProgress {
    phase: string
    step: number
    total_steps: number
    // Optional: the backend's fallback tick omits these keys entirely.
    phase_elapsed_s?: number | null
    rasterizer?: ObservationRasterizerProgress | null
}

export interface DisplayPhase {
    label: string
    weight: number
    /** Time constant (seconds) for the time-based fill. */
    tauS: number
}

// Weights and time constants follow measured production phase durations; only rendering has real progress (frames).
export const DISPLAY_PHASES: DisplayPhase[] = [
    { label: 'Preparing recording', weight: 20, tauS: 20 },
    { label: 'Rendering video', weight: 25, tauS: 15 },
    { label: 'Analyzing recording', weight: 53, tauS: 45 },
    { label: 'Finishing up', weight: 2, tauS: 2 },
]

const RENDERING_STEP = 1

// A time-based fill stops short of its phase's end, so the next phase's real start is never a step back.
const TIME_FILL_CAP = 0.9

export function framesOf(progress: ObservationProgress | null): ObservationFrameProgress | null {
    const frames = progress?.rasterizer?.frame_progress
    if (!frames || frames.estimatedTotalFrames <= 0 || frames.phase === 'setup') {
        return null
    }
    return frames
}

/** Rendering counts only once frames exist, so the rasterizer queue and browser setup read as preparing. */
export function displayStepFor(progress: ObservationProgress): number {
    switch (progress.phase) {
        case 'rendering':
            return framesOf(progress) ? RENDERING_STEP : 0
        case 'uploading':
        case 'analyzing':
            return 2
        case 'finalizing':
            return 3
        default:
            return 0
    }
}

export function isRenderingStep(step: number): boolean {
    return step === RENDERING_STEP
}

export function overallPercent(step: number, stepElapsedS: number, frames: ObservationFrameProgress | null): number {
    const phase = DISPLAY_PHASES[step]
    const before = DISPLAY_PHASES.slice(0, step).reduce((sum, p) => sum + p.weight, 0)
    const fill =
        isRenderingStep(step) && frames
            ? Math.min(frames.frame / frames.estimatedTotalFrames, 1)
            : (1 - Math.exp(-Math.max(0, stepElapsedS) / phase.tauS)) * TIME_FILL_CAP
    return before + phase.weight * fill
}

import { memo, useCallback, useEffect, useRef, useState } from 'react'

import { Button } from '@posthog/quill-primitives'

import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

import type { OnboardingStep } from './onboardingSteps'

// One wrapper for both branches, so a recorded clip drops into the same box the glyph occupied and the
// dialog does not resize when the media lands.
const PANEL = 'PhaiOnboardingTakeover__media relative w-full overflow-hidden rounded-md aspect-video'
// Every step's clip is stacked in that box; only the current one is opaque.
const LAYER = 'absolute inset-0 motion-safe:transition-opacity motion-safe:duration-150'
/**
 * How long a clip holds its first frame after its step arrives, so the headline gets the eye first. Every
 * clip opens on a picture rather than a blank stage, so the wait costs nothing and the opening beats are
 * no longer spent while the reader is still on the text above them.
 */
const PLAYBACK_DELAY_MS = 550

function prefersReducedMotion(): boolean {
    return (
        typeof window !== 'undefined' &&
        typeof window.matchMedia === 'function' &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches
    )
}

function inStorybookEnvironment(): boolean {
    return inStorybook() || inStorybookTestRunner()
}

// Hold every clip on its poster frame under Storybook so visual snapshots don't race the decoder.
function shouldAutoplay(): boolean {
    return !prefersReducedMotion() && !inStorybookEnvironment()
}

/**
 * The play control is the reduced-motion accommodation, so it follows the preference rather than whatever
 * suppressed autoplay. Storybook suppresses autoplay too, and gating the button on that would paint it into
 * every visual snapshot of a panel that no reader sees it on.
 */
function showsPlayControl(): boolean {
    return prefersReducedMotion() && !inStorybookEnvironment()
}

export interface OnboardingMediaPanelProps {
    steps: readonly OnboardingStep[]
    stepIndex: number
    /** Clips play only while the dialog is open. */
    open: boolean
    onReplay?: (step: OnboardingStep) => void
}

/**
 * The dialog's media panel: every step's clip at once, stacked, with the current one faded up.
 *
 * Mounting them all is what makes stepping between slides clean. Pointing a single `<video>` at a new `src`
 * tears down the element's media state, so the panel would paint the incoming clip's poster, wait on the
 * network, and only then cut to its first frame. Held side by side the clips are already decoded and parked
 * on frame 0, so a step change is a crossfade between two live frames. The set is about 1.7 MB, fetched once
 * when the dialog opens.
 */
export const OnboardingMediaPanel = memo(function OnboardingMediaPanel({
    steps,
    stepIndex,
    open,
    onReplay,
}: OnboardingMediaPanelProps): JSX.Element {
    return (
        <div className={PANEL}>
            {steps.map((step, index) => (
                <OnboardingStepMedia
                    key={step.key}
                    step={step}
                    visible={index === stepIndex}
                    active={open && index === stepIndex}
                    onReplay={onReplay}
                />
            ))}
        </div>
    )
})

interface OnboardingStepMediaProps {
    step: OnboardingStep
    /** The one layer the reader sees. The rest sit under it at zero opacity, still loaded. */
    visible: boolean
    /** The clip only plays while its own step is the visible one. */
    active: boolean
    onReplay?: (step: OnboardingStep) => void
}

/**
 * One step's looping demo clip. Follows the desktop app's onboarding card (`FeatureBentoCard`): the clip is
 * parked on its poster frame, playback is driven imperatively rather than via `autoplay`/`loop`, and it
 * loops back to `startTime` instead of 0 so the rest position always matches the poster. When motion is
 * reduced the clip holds the still and offers an explicit play control.
 */
const OnboardingStepMedia = memo(function OnboardingStepMedia({
    step,
    visible,
    active,
    onReplay,
}: OnboardingStepMediaProps): JSX.Element {
    const videoRef = useRef<HTMLVideoElement>(null)
    const [manuallyPlaying, setManuallyPlaying] = useState(false)
    const media = step.media
    const startTime = media?.startTime ?? 0

    const play = useCallback((video: HTMLVideoElement): void => {
        try {
            // jsdom stubs `play()` to return undefined rather than a promise, so this can't assume one.
            void video.play()?.catch(() => {
                // play() rejects if the element isn't ready yet; the next effect run retries.
            })
        } catch {
            // No media support at all (jsdom throws outright on some versions).
        }
    }, [])

    const seekToStart = useCallback(
        (video: HTMLVideoElement): void => {
            try {
                video.currentTime = startTime
            } catch {
                // Seeking before metadata is ready is a no-op; `loadedmetadata` retries it.
            }
        },
        [startTime]
    )

    useEffect(() => {
        const video = videoRef.current
        if (!video) {
            return
        }
        if (video.readyState >= 1) {
            seekToStart(video)
            return
        }
        const handler = (): void => seekToStart(video)
        video.addEventListener('loadedmetadata', handler, { once: true })
        return () => video.removeEventListener('loadedmetadata', handler)
    }, [media?.src, seekToStart])

    useEffect(() => {
        const video = videoRef.current
        if (!video) {
            return
        }
        if (!active) {
            // Paused where it stood, not rewound: the outgoing clip holds its last frame through the
            // crossfade, and rewinding is the incoming clip's job below.
            video.pause()
            setManuallyPlaying(false)
            return
        }
        seekToStart(video)
        if (!shouldAutoplay()) {
            return
        }
        // Cleared when the step changes, so stepping quickly through the dialog never starts a clip the
        // reader has already moved past.
        const timer = window.setTimeout(() => play(video), PLAYBACK_DELAY_MS)
        return () => window.clearTimeout(timer)
        // `manuallyPlaying` is deliberately not a dependency: it's reset here, and including it would make
        // this effect cancel the very playback the play button just started.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [active, play, seekToStart])

    const handleEnded = useCallback((): void => {
        const video = videoRef.current
        if (!video) {
            return
        }
        seekToStart(video)
        if (active && shouldAutoplay()) {
            play(video)
        } else {
            setManuallyPlaying(false)
        }
    }, [active, play, seekToStart])

    const handlePlayClick = useCallback((): void => {
        const video = videoRef.current
        if (!video) {
            return
        }
        setManuallyPlaying(true)
        play(video)
        onReplay?.(step)
    }, [onReplay, play, step])

    if (!media) {
        return (
            <div
                className={cn(LAYER, 'flex items-center justify-center', !visible && 'pointer-events-none opacity-0')}
                aria-hidden
            >
                {/* Large and low-contrast: a small faint mark in a 306px panel reads as a missing asset,
                    the same mark at this scale reads as the step's own artwork. */}
                <span className="text-[6rem] leading-none text-[var(--foreground)] opacity-15">{step.icon}</span>
            </div>
        )
    }

    return (
        <div className={cn(LAYER, !visible && 'pointer-events-none opacity-0')} aria-hidden={!visible}>
            <video
                ref={videoRef}
                className="block h-full w-full object-cover"
                src={media.src}
                poster={media.poster}
                muted
                playsInline
                // Every clip is decoded up front so that stepping between slides never waits on the network.
                preload="auto"
                aria-label={step.headline}
                onEnded={handleEnded}
            />
            {visible && showsPlayControl() && !manuallyPlaying && (
                <Button
                    variant="primary"
                    size="sm"
                    // Bottom-left, because every clip now carries the composer, whose send button sits in
                    // the bottom-right corner of the frame.
                    className="absolute bottom-2 start-2"
                    onClick={handlePlayClick}
                    data-attr="posthog-ai-onboarding-play-clip"
                >
                    Play
                </Button>
            )}
        </div>
    )
})

import bubblesUrl from 'public/sounds/bubbles.mp3'
import daniloUrl from 'public/sounds/danilo.mp3'
import dropUrl from 'public/sounds/drop.mp3'
import guitarUrl from 'public/sounds/guitar.mp3'
import icqUrl from 'public/sounds/icq.mp3'
import knockUrl from 'public/sounds/knock.mp3'
import meepSmolUrl from 'public/sounds/meep-smol.mp3'
import meepUrl from 'public/sounds/meep.mp3'
import msnUrl from 'public/sounds/msn.mp3'
import reviUrl from 'public/sounds/revi.mp3'
import ringUrl from 'public/sounds/ring.mp3'
import shootUrl from 'public/sounds/shoot.mp3'
import slideUrl from 'public/sounds/slide.mp3'
import switchUrl from 'public/sounds/switch.mp3'
import wilhelmUrl from 'public/sounds/wilhelm.mp3'

/** The same built-in set as PostHog Desktop, so a sound picked there has a match here. */
export const BUILT_IN_TURN_SOUNDS = {
    meep: { label: 'Meep', url: meepUrl },
    'meep-smol': { label: 'Meep (smol)', url: meepSmolUrl },
    guitar: { label: 'Guitar solo', url: guitarUrl },
    danilo: { label: "I'm ready", url: daniloUrl },
    revi: { label: 'Cute noise', url: reviUrl },
    bubbles: { label: 'Bubbles', url: bubblesUrl },
    drop: { label: 'Drop', url: dropUrl },
    knock: { label: 'Knock', url: knockUrl },
    ring: { label: 'Ring', url: ringUrl },
    shoot: { label: 'Shoot', url: shootUrl },
    slide: { label: 'Slide', url: slideUrl },
    switch: { label: 'Switch', url: switchUrl },
    wilhelm: { label: 'Wilhelm scream', url: wilhelmUrl },
    icq: { label: 'ICQ', url: icqUrl },
    msn: { label: 'MSN Messenger', url: msnUrl },
} as const

export type BuiltInTurnSound = keyof typeof BUILT_IN_TURN_SOUNDS
export type TurnSound = 'none' | 'custom' | BuiltInTurnSound

export const TURN_SOUND_OPTIONS: { value: TurnSound; label: string }[] = [
    { value: 'none', label: 'No sound' },
    ...Object.entries(BUILT_IN_TURN_SOUNDS).map(([value, { label }]) => ({ value: value as TurnSound, label })),
]

export interface CustomTurnSound {
    name: string
    /** Stored inline as a data URL in localStorage, so the upload size is capped. */
    dataUrl: string
}

export const MAX_CUSTOM_TURN_SOUND_BYTES = 500_000
export const MAX_CUSTOM_TURN_SOUND_SECONDS = 5
// Decoders can report a duration a little over the real one.
const DURATION_TOLERANCE_SECONDS = 0.3

export function resolveTurnSoundUrl(sound: TurnSound, customSound: CustomTurnSound | null): string | null {
    if (sound === 'none') {
        return null
    }
    if (sound === 'custom') {
        return customSound?.dataUrl ?? null
    }
    return BUILT_IN_TURN_SOUNDS[sound]?.url ?? null
}

let currentAudio: HTMLAudioElement | null = null

export function playTurnSound(url: string, volume: number): void {
    // Stop the previous sound so two quick turns do not overlap.
    currentAudio?.pause()
    const audio = new Audio(url)
    audio.volume = Math.max(0, Math.min(100, volume)) / 100
    currentAudio = audio
    // The browser blocks audio until the user interacts with the page. Stay quiet then.
    void audio.play().catch(() => undefined)
}

export function readFileAsDataUrl(file: File): Promise<string> {
    return new Promise((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(reader.result as string)
        reader.onerror = () => reject(reader.error ?? new Error('Could not read the file'))
        reader.readAsDataURL(file)
    })
}

/** Resolves to the clip length in seconds, or null when the browser cannot decode the file. */
export function readAudioDuration(url: string): Promise<number | null> {
    return new Promise((resolve) => {
        const audio = new Audio()
        audio.preload = 'metadata'
        audio.onloadedmetadata = () => resolve(Number.isFinite(audio.duration) ? audio.duration : null)
        audio.onerror = () => resolve(null)
        audio.src = url
    })
}

export function isCustomTurnSoundTooLong(durationSeconds: number): boolean {
    return durationSeconds > MAX_CUSTOM_TURN_SOUND_SECONDS + DURATION_TOLERANCE_SECONDS
}

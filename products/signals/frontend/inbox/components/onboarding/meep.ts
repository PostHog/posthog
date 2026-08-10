import { lemonToast } from '@posthog/lemon-ui'

import meepUrl from 'public/sounds/meep.mp3'

let audio: HTMLAudioElement | null = null

/**
 * Clicking an (otherwise inert) onboarding sample card plays a "meep" – a nod to PostHog Desktop –
 * and pops a toast. The toast explains that the card is an example and how to get real work, so a
 * click reads as an answer rather than a stray debug word. The sound stays as the flair; it is no
 * longer the only thing a click says. Pure UI feedback; nothing else depends on it.
 */
export function playMeep(): void {
    lemonToast.info('This is an example. Run the setup command in your repo to get real reports in your inbox.')
    try {
        // Reuse one element across clicks; rewind so rapid clicks restart the sound rather than overlap.
        if (!audio) {
            audio = new Audio(meepUrl)
            audio.volume = 0.8
        }
        audio.currentTime = 0
        // Autoplay can be blocked until the page has been interacted with; a click satisfies that,
        // but ignore any rejection (and jsdom, which doesn't implement playback) regardless.
        void audio.play().catch(() => {})
    } catch {
        // Audio unsupported in this environment – the toast alone is fine.
    }
}

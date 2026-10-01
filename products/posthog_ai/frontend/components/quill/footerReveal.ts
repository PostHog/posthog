/**
 * Classes for a message footer that fades in on hover. The footer takes pointer input only once the fade
 * ends, so a pointer that passes over it on the way in does not open the timestamp popover early.
 */
export function footerRevealClass(revealed: boolean): string {
    return revealed
        ? 'opacity-100 [transition:opacity_150ms,pointer-events_0s_150ms] [transition-behavior:allow-discrete]'
        : 'pointer-events-none opacity-0 transition-opacity duration-150 focus-within:pointer-events-auto focus-within:opacity-100'
}

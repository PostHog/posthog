/**
 * Classes for a message footer that fades in on hover. The footer takes pointer input only once the fade
 * ends, so a pointer that passes over it on the way in does not open the timestamp popover early.
 */
export function footerRevealClass(revealed: boolean): string {
    return revealed
        ? '[--footer-fade:150ms] opacity-100 [transition:opacity_var(--footer-fade),pointer-events_0s_var(--footer-fade)_allow-discrete]'
        : '[--footer-fade:150ms] pointer-events-none opacity-0 [transition:opacity_var(--footer-fade)] focus-within:pointer-events-auto focus-within:opacity-100'
}

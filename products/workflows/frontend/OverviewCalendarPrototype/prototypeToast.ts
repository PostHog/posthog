// PROTOTYPE (throwaway): stands in for pages the invented data has no route to.
import { lemonToast } from '@posthog/lemon-ui'

export function prototypeToast(what: string): void {
    lemonToast.info(`In the build, this opens ${what}.`)
}

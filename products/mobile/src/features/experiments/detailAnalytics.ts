import { track } from '@/lib/analytics'

import type { AboutWhat } from './aboutCopy'

// Typed wrappers for the experiment screen's own events. The list and action events have theirs next to their screens.

/**
 * `started`: a pull started or joined a recalculation. `window`: the server's five-minute window refused it, so the
 * pull re-read the stored results. `reread`: no recalculation applies (complete, draft, too old to recalculate).
 * `failed`: the request failed.
 */
export type ResultsRefreshOutcome = 'started' | 'window' | 'reread' | 'failed'

/** `approval` is the change request a held ship opens on the web. */
export type ExperimentWebTarget = 'experiment' | 'flag' | 'approval'

export function trackExperimentResultsRefreshed(props: { outcome: ResultsRefreshOutcome }): void {
    track('mobile_experiment_results_refreshed', { outcome: props.outcome })
}

export function trackExperimentNumberExplained(props: { what: AboutWhat }): void {
    track('mobile_experiment_number_explained', { what: props.what })
}

export function trackExperimentHypothesisToggled(props: { expanded: boolean }): void {
    track('mobile_experiment_hypothesis_toggled', { expanded: props.expanded })
}

export function trackExperimentChatOpened(): void {
    track('mobile_experiment_chat_opened')
}

export function trackExperimentLinkCopied(): void {
    track('mobile_experiment_link_copied')
}

export function trackExperimentOpenedInWeb(props: { target: ExperimentWebTarget }): void {
    track('mobile_experiment_opened_in_web', { target: props.target })
}

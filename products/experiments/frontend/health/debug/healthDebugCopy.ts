import type { HealthDebugDomain } from './healthDebugReport'

export const HEALTH_DEBUG_DOMAINS: HealthDebugDomain[] = [
    'experiment',
    'flag',
    'exposures',
    'metrics',
    'project',
    'raw',
]

export const HEALTH_DEBUG_TITLE = 'Health checks debug'
export const HEALTH_DEBUG_DESCRIPTION =
    "What each health check concluded, and the inputs it read. Customers don't see this tab."
export const CHECK_RESULTS_TITLE = 'Check results'
export const CHECK_RESULTS_DESCRIPTION = 'One row per check. The buttons under Reads open the inputs the check reads.'
export const INPUTS_TITLE = 'Inputs'
export const INPUTS_DESCRIPTION = 'The values the checks read, grouped by domain.'
export const EXPOSURES_INPUT_NOTE =
    "The exposure query's cached answer that the zero-exposures, SRM and bias checks read on the server."
export const DRIFT_TOOLTIP =
    "The page's exposure answer is cached apart from the server's and computed at another time, so the two can differ. The panel shows the page's."

export const FLAG_CONFIGURATION_TITLE = 'Configuration'
export const FLAG_CONFIGURATION_DESCRIPTION = 'The flag as the health checks read it on the server.'
export const FLAG_CHANGES_TITLE = 'Changes since launch'
export const FLAG_CHANGES_DESCRIPTION =
    "What the split, bucketing and release-condition checks read from the flag's history."
export const FLAG_TRAFFIC_TITLE = 'Calls by release condition'
export const FLAG_TRAFFIC_DESCRIPTION =
    "The flag's recent calls that the forced-variant and release-condition checks grade overrides by."
export const NO_RELEASE_CONDITIONS = 'No release conditions.'

export const PROJECT_FACTS_NOT_LOADED = 'The project facts did not load. Reload the inputs to try again.'
export const PROJECT_FACTS_DESCRIPTION =
    'Project-wide facts, read by the same providers as the setup context. No check reads them yet. They help explain a finding, for example when flags are evaluated outside the flag service.'
export const SDK_PROFILE_SKIPPED = 'Skipped, because you may not query events or are denied a property it reads.'

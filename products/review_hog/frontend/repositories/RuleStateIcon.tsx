import { IconBuilding } from '@posthog/icons'

import type { AutomaticFlashForEnumApi } from 'products/review_hog/frontend/generated/api.schemas'

const RULE_STATE_COLORS: Record<AutomaticFlashForEnumApi, string> = {
    everyone: 'text-success',
    listed: 'text-warning',
    off: 'text-tertiary',
}

/** The project building, colored by how many people a rule reviews: everyone, some people, or nobody by default. */
export function RuleStateIcon({ flashFor }: { flashFor: AutomaticFlashForEnumApi }): JSX.Element {
    return <IconBuilding className={`shrink-0 text-base ${RULE_STATE_COLORS[flashFor]}`} />
}

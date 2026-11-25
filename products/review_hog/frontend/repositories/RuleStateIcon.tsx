import { DotState, StateDot } from 'lib/components/RepositoryList/StateDot'

import type { AutomaticFlashForEnumApi } from 'products/review_hog/frontend/generated/api.schemas'

const RULE_DOT_STATE: Record<AutomaticFlashForEnumApi, DotState> = {
    everyone: 'on',
    listed: 'partial',
    off: 'off',
}

/** How much of the team a rule reviews: everyone, some people, or nobody. */
export function RuleStateIcon({ flashFor }: { flashFor: AutomaticFlashForEnumApi }): JSX.Element {
    return <StateDot state={RULE_DOT_STATE[flashFor]} />
}

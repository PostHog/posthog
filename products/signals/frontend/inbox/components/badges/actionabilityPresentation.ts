import type { LemonTagType } from '@posthog/lemon-ui'

import { SignalReportActionability } from '../../types'

export interface ActionabilityPresentation {
    type: LemonTagType
    label: string
    tooltip: string
}

/** Label, tone and meaning of each actionability, shared by the Lemon and quill actionability badges. */
export const ACTIONABILITY_PRESENTATION: Record<SignalReportActionability, ActionabilityPresentation> = {
    immediately_actionable: {
        type: 'success',
        label: 'Actionable',
        tooltip:
            "The report can be solved with code. If there isn't a pull request yet, it fell below your auto-PR priority threshold. You can still start one from this report.",
    },
    requires_human_input: {
        type: 'caution',
        label: 'Needs input',
        tooltip:
            'Actionable, but it needs your input first to decide how to resolve it: business context, trade-offs, or a choice between several valid approaches.',
    },
    not_actionable: {
        type: 'muted',
        label: 'Not actionable',
        tooltip:
            'No useful code change can be derived because the report is too vague, lacks supporting evidence, or describes expected behavior.',
    },
}

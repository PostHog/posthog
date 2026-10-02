import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import type {
    PersonalInboxEntryApi,
    PersonalNextActionKindEnumApi,
    PersonalReasonEnumApi,
} from 'products/signals/frontend/generated/api.schemas'

const NEXT_ACTION_LABEL: Record<PersonalNextActionKindEnumApi, string> = {
    review_finding: 'Review finding',
    answer_question: 'Answer question',
    review_pr: 'Review PR',
    check_pr: 'Check PR status',
    resolve_blocker: 'Resolve blocker',
    continue_work: 'Continue work',
}

function reasonText(reasons: PersonalReasonEnumApi[]): string | null {
    const reviewer = reasons.includes('suggested_reviewer')
    const claimed = reasons.includes('claimed')
    if (reviewer && claimed) {
        return "You're a suggested reviewer and you claimed this."
    }
    if (reviewer) {
        return "You're a suggested reviewer."
    }
    if (claimed) {
        return 'You claimed this.'
    }
    return null
}

/** The step the personal inbox asks of the viewer on a report row, or the state it waits in. */
export function PersonalInboxNextStepTag({ entry }: { entry: PersonalInboxEntryApi }): JSX.Element | null {
    let label: string
    let detail: string | null = null
    if (entry.next_action) {
        label = NEXT_ACTION_LABEL[entry.next_action.kind]
    } else if (entry.action_state === 'waiting') {
        label = 'Waiting'
        detail = 'An agent or another person has to act first.'
    } else if (entry.action_state === 'unknown') {
        label = 'State unknown'
        detail = "The current state isn't confirmed yet."
    } else {
        return null
    }
    const tooltip = [detail, reasonText(entry.reasons)].filter(Boolean).join(' ')

    return (
        <Tooltip title={tooltip || undefined}>
            <span className="inline-flex min-w-0 max-w-full">
                <LemonTag
                    size="small"
                    type={entry.next_action ? 'default' : 'muted'}
                    className="max-w-full truncate select-none"
                    data-attr="inbox-report-personal-next-step"
                >
                    {label}
                </LemonTag>
            </span>
        </Tooltip>
    )
}

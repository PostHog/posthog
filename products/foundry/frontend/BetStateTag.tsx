import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { BetRecord } from './foundryLogic'

const STATE_TAG_TYPE: Record<string, LemonTagType> = {
    drafted: 'default',
    funded: 'highlight',
    building: 'warning',
    gated: 'completion',
    exposed: 'success',
    archived: 'muted',
}

const VERDICT_TAG_TYPE: Record<string, LemonTagType> = {
    promoted: 'success',
    rolled_back: 'danger',
}

export function BetStateTag({ bet }: { bet: BetRecord }): JSX.Element {
    return (
        <span className="flex gap-1">
            <LemonTag type={STATE_TAG_TYPE[bet.state] ?? 'default'}>{bet.state}</LemonTag>
            {bet.verdict ? <LemonTag type={VERDICT_TAG_TYPE[bet.verdict] ?? 'default'}>{bet.verdict}</LemonTag> : null}
        </span>
    )
}

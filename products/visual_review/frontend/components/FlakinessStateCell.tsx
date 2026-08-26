import { IconWarning } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import type { FlakinessEntryApi } from '../generated/api.schemas'

const STATE_TAG: Record<string, { label: string; type: 'danger' | 'warning' | 'success' }> = {
    unstable: { label: 'Unstable', type: 'danger' },
    settled: { label: 'Settled', type: 'warning' },
    clean: { label: 'Clean', type: 'success' },
}

export function StateCell({ entry }: { entry: FlakinessEntryApi }): JSX.Element {
    const tag = STATE_TAG[entry.flakiness_state] ?? STATE_TAG.clean
    return (
        <div className="flex flex-col gap-1 items-start">
            <LemonTag type={tag.type}>{tag.label}</LemonTag>
            {entry.is_quarantined && (
                <LemonTag type="warning" icon={<IconWarning />}>
                    Quarantined
                </LemonTag>
            )}
        </div>
    )
}

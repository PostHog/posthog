import { IconWarning } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import type { FlakinessEntryApi } from '../generated/api.schemas'

const STATE_TAG: Record<
    string,
    { label: string; type: 'danger' | 'caution' | 'warning' | 'success' | 'muted'; title: string }
> = {
    broken: {
        label: 'Broken',
        type: 'danger',
        title: 'Fails nearly every run. Its baseline no longer matches what the story renders, or it never got one, so fix the baseline rather than quarantine it.',
    },
    unstable: {
        label: 'Unstable',
        type: 'caution',
        title: 'Fails some runs and not others. Stabilize the story, or quarantine it while you do.',
    },
    at_risk: {
        label: 'At risk',
        type: 'warning',
        title: 'Never fails today, but its worst diff is already close to the threshold. The next unrelated rendering change turns it red.',
    },
    noisy: {
        label: 'Noisy',
        type: 'muted',
        title: 'Renders more than one image, and the tolerated variants absorb it with room to spare. Nothing to do.',
    },
    clean: {
        label: 'Clean',
        type: 'success',
        title: 'Matched its baseline on every run in the window.',
    },
}

export function StateCell({ entry }: { entry: FlakinessEntryApi }): JSX.Element {
    const tag = STATE_TAG[entry.flakiness_state] ?? STATE_TAG.clean
    return (
        <div className="flex flex-col gap-1 items-start">
            <LemonTag type={tag.type} title={tag.title}>
                {tag.label}
            </LemonTag>
            {entry.is_quarantined && (
                <LemonTag type="warning" icon={<IconWarning />} title="Skipped when a run decides pass or fail">
                    Quarantined
                </LemonTag>
            )}
        </div>
    )
}

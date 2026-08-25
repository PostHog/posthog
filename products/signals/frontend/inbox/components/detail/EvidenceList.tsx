import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { signalCardSourceLine } from 'lib/signals/signalCardSourceLine'
import { SignalNode } from 'scenes/debug/signals/types'

import { SignalCard } from '../../SignalCard'
import {
    GROUP_PREVIEW_COUNT,
    groupReportSignals,
    shouldGroupSignals,
    SignalSourceGroup,
} from '../../utils/signalGrouping'

export function EvidenceList({ signals }: { signals: SignalNode[] }): JSX.Element {
    if (!shouldGroupSignals(signals)) {
        return (
            <div className="flex flex-col gap-3">
                {signals.map((signal) => (
                    <SignalCard key={signal.signal_id} signal={signal} />
                ))}
            </div>
        )
    }
    return (
        <div className="flex flex-col gap-4">
            {groupReportSignals(signals).map((group) => (
                <SignalSourceGroupSection key={group.key} group={group} />
            ))}
        </div>
    )
}

function SignalSourceGroupSection({ group }: { group: SignalSourceGroup<SignalNode> }): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const visible = expanded ? group.signals : group.signals.slice(0, GROUP_PREVIEW_COUNT)
    const hiddenCount = group.signals.length - visible.length

    return (
        <section className="flex flex-col gap-2">
            <h4 className="m-0 flex items-baseline gap-1.5 text-xs font-medium text-tertiary leading-none select-none">
                <span className="min-w-0 truncate">{signalCardSourceLine(group.signals[0])}</span>
                <span className="tabular-nums">{group.signals.length}</span>
            </h4>
            <div className="flex flex-col gap-3">
                {visible.map((signal) => (
                    <SignalCard key={signal.signal_id} signal={signal} />
                ))}
            </div>
            {hiddenCount > 0 && (
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    className="self-start"
                    onClick={() => setExpanded(true)}
                    data-attr="inbox-evidence-show-all"
                >
                    Show all {group.signals.length}
                </LemonButton>
            )}
        </section>
    )
}

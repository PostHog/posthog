import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { inboxSceneLogic } from '../../../inboxSceneLogic'
import { entriesForSkill, scratchpadLogic } from '../../../logics/scratchpadLogic'
import { ScratchpadEntryCard } from '../../scratchpad/ScratchpadEntryCard'

const INITIAL_VISIBLE = 3

/**
 * What this scout has worked out for itself — the slice of the fleet scratchpad it wrote. Baselines
 * it settled on, things it ruled out, vocabulary it learned. This is the difference between a
 * scout that looks like a cron job and one that visibly gets better at its job.
 */
export function ScoutLearnedPanel({ skillName }: { skillName: string }): JSX.Element | null {
    const { entries, entriesLoading, loadFailed } = useValues(scratchpadLogic)
    const { loadEntries } = useActions(scratchpadLogic)
    const { setScratchpadOpen } = useActions(inboxSceneLogic)
    const [showAll, setShowAll] = useState(false)

    if (entriesLoading && entries === null) {
        return (
            <div className="flex flex-col gap-2">
                <span className="text-xs font-medium uppercase tracking-wide text-default">What it has learned</span>
                <LemonSkeleton className="h-16 w-full rounded" />
            </div>
        )
    }

    // A failed load is not an empty memory: say so, rather than silently dropping the panel.
    if (loadFailed && entries === null) {
        return (
            <div className="flex flex-col gap-2">
                <span className="text-xs font-medium uppercase tracking-wide text-default">What it has learned</span>
                <div className="flex flex-col items-center gap-2 rounded border border-danger bg-danger-highlight px-4 py-6 text-center text-sm text-danger">
                    <span>Couldn't load what this scout has learned.</span>
                    <LemonButton size="xsmall" type="secondary" onClick={() => loadEntries()}>
                        Try again
                    </LemonButton>
                </div>
            </div>
        )
    }

    const scoutEntries = entriesForSkill(entries, skillName)
    // Plenty of scouts never write a note. An empty box would say less than no box at all.
    if (scoutEntries.length === 0) {
        return null
    }

    const visible = showAll ? scoutEntries : scoutEntries.slice(0, INITIAL_VISIBLE)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
                <span className="text-xs font-medium uppercase tracking-wide text-default">What it has learned</span>
                <span className="text-xs text-muted">{pluralize(scoutEntries.length, 'entry', 'entries')}</span>
                <span className="flex-1" />
                <LemonButton size="xsmall" type="tertiary" onClick={() => setScratchpadOpen(true)}>
                    All scouts
                </LemonButton>
            </div>
            <div className="flex flex-col gap-2">
                {visible.map((entry) => (
                    <ScratchpadEntryCard key={entry.key} entry={entry} />
                ))}
            </div>
            {scoutEntries.length > visible.length && (
                <LemonButton size="xsmall" type="tertiary" className="self-start" onClick={() => setShowAll(true)}>
                    Show all {pluralize(scoutEntries.length, 'entry', 'entries')}
                </LemonButton>
            )}
        </div>
    )
}

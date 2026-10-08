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
export function ScoutLearnedPanel({ skillName }: { skillName: string }): JSX.Element {
    const { entries, entriesLoading, loadFailed } = useValues(scratchpadLogic)
    const { loadEntries } = useActions(scratchpadLogic)
    const { setScratchpadOpen } = useActions(inboxSceneLogic)
    const [showAll, setShowAll] = useState(false)

    if (entriesLoading && entries === null) {
        return <LemonSkeleton className="h-16 w-full rounded" />
    }

    // A failed load is not an empty memory: say so, rather than silently showing nothing.
    if (loadFailed && entries === null) {
        return (
            <div className="flex flex-col items-center gap-2 rounded border border-danger bg-danger-highlight px-4 py-6 text-center text-sm text-danger">
                <span>Couldn't load what this scout has learned.</span>
                <LemonButton size="xsmall" type="secondary" onClick={() => loadEntries()}>
                    Try again
                </LemonButton>
            </div>
        )
    }

    const scoutEntries = entriesForSkill(entries, skillName)
    const visible = showAll ? scoutEntries : scoutEntries.slice(0, INITIAL_VISIBLE)

    return (
        <div className="flex flex-col gap-2">
            {scoutEntries.length === 0 ? (
                <div className="rounded border border-dashed border-primary bg-surface-primary px-4 py-6 text-center text-sm text-muted">
                    Nothing yet. Scouts write here when they settle on a baseline or rule something out.
                </div>
            ) : (
                <>
                    {visible.map((entry) => (
                        <ScratchpadEntryCard key={entry.key} entry={entry} titled />
                    ))}
                    {scoutEntries.length > visible.length && (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            className="self-start"
                            onClick={() => setShowAll(true)}
                        >
                            Show all {pluralize(scoutEntries.length, 'entry', 'entries')}
                        </LemonButton>
                    )}
                </>
            )}
            <LemonButton size="xsmall" type="tertiary" className="self-start" onClick={() => setScratchpadOpen(true)}>
                All scouts
            </LemonButton>
        </div>
    )
}

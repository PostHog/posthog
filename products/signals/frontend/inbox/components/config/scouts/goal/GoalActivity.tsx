import { useState } from 'react'

import { LemonButton, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import type { GoalScoutActivityApi } from 'products/signals/frontend/generated/api.schemas'

import { groupActivity } from '../../../../utils/goal/format'
import { GoalActivityRow } from './GoalActivityRow'

const SHOWN = 10

export function GoalActivity({
    entries,
    loading,
    error,
    onRefresh,
}: {
    entries: GoalScoutActivityApi[] | null
    loading: boolean
    error: string | null
    onRefresh: () => void
}): JSX.Element {
    const [all, setAll] = useState(false)
    const groups = groupActivity(entries ?? [])
    const shown = all ? groups : groups.slice(0, SHOWN)
    return (
        <SceneSection title="Activity" titleSize="sm" className="gap-y-2">
            {loading && !entries ? (
                <LemonSkeleton className="h-24 w-full" />
            ) : error && !entries ? (
                <div className="flex items-center gap-2 text-xs text-danger" role="alert">
                    Couldn't load the activity.
                    <LemonButton size="xsmall" type="secondary" onClick={onRefresh}>
                        Try again
                    </LemonButton>
                </div>
            ) : !shown.length ? (
                <p className="m-0 text-xs text-secondary">Nothing has happened on this goal yet.</p>
            ) : (
                <ul className="m-0 -mx-1 flex list-none flex-col p-0">
                    {shown.map((group) => (
                        <GoalActivityRow key={group[0].id} group={group} />
                    ))}
                </ul>
            )}
            {groups.length > SHOWN && (
                <Link subtle className="self-start text-xs" onClick={() => setAll(!all)} data-attr="goal-activity-all">
                    {all ? 'Show less' : `Show all ${groups.length}`}
                </Link>
            )}
        </SceneSection>
    )
}

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import type { GoalScoutDetailApi, GoalScoutWorkApi } from 'products/signals/frontend/generated/api.schemas'

import { isBuilt, waitingIdeas } from '../../../../utils/goal/ideas'
import { isOpen } from '../../../../utils/goal/status'
import { GoalWorkRow } from './GoalWorkRow'

const latest = (item: GoalScoutWorkApi): number => Date.parse(item.finished_at ?? item.chosen_at ?? item.created_at)

export function GoalProgress({ goal }: { goal: GoalScoutDetailApi }): JSX.Element {
    const built = goal.work.filter(isBuilt)
    const open = built.filter(isOpen).sort((a, b) => latest(b) - latest(a))
    const finished = built.filter((item) => !isOpen(item)).sort((a, b) => latest(b) - latest(a))
    const ended = finished.filter((item) => item.kind === 'idea')
    const tests = ended.filter((item) => item.outcome && item.outcome !== 'dropped')
    const dropped = ended.length - tests.length
    const hint = built.length
        ? [
              open.length ? `${open.length} in progress` : 'Nothing in progress',
              tests.length ? `${tests.length} ${tests.length === 1 ? 'idea' : 'ideas'} tested` : '',
              dropped ? `${dropped} dropped` : '',
          ]
              .filter(Boolean)
              .join(' · ')
        : undefined
    return (
        <SceneSection title="Progress" description={hint} titleSize="sm" className="gap-y-2">
            {!built.length ? (
                <p className="m-0 text-sm text-secondary">
                    {waitingIdeas(goal).length
                        ? 'Nothing is built yet. Choose an idea above to start.'
                        : 'The scout is getting started. The first step checks how the goal is measured.'}
                </p>
            ) : (
                [...open, ...finished].map((item) => <GoalWorkRow key={item.id} item={item} goal={goal} />)
            )}
        </SceneSection>
    )
}

import { useActions, useValues } from 'kea'

import { IconLightBulb, IconPlus } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import type { GoalScoutDetailApi } from 'products/signals/frontend/generated/api.schemas'

import { goalScoutLogic } from '../../../../logics/goal/goalScoutLogic'
import { GoalAddIdeaForm } from './GoalAddIdeaForm'
import { GoalBuildModal } from './GoalBuildModal'
import { GoalIdeaRow } from './GoalIdeaRow'
import { GoalRow } from './GoalRow'

export function GoalIdeas({ goal }: { goal: GoalScoutDetailApi }): JSX.Element | null {
    const {
        waitingIdeas,
        dismissedIdeas,
        ideaInProgress,
        addingIdea,
        laterOpen,
        dismissedOpen,
        ideaError,
        buildDisabledReason,
        busy,
    } = useValues(goalScoutLogic({ id: goal.id }))
    const { setAddingIdea, setLaterOpen, setDismissedOpen } = useActions(goalScoutLogic({ id: goal.id }))
    const canAdd = goal.is_owner && goal.state.can_add_idea
    const scoutRunning = goal.scout_running
    if (!waitingIdeas.length && !dismissedIdeas.length && !canAdd && !scoutRunning && !ideaInProgress) {
        return null
    }
    const ready = goal.state.ready_ideas
    const summary = ideaInProgress
        ? waitingIdeas.length
            ? `${waitingIdeas.length} ${waitingIdeas.length === 1 ? 'idea waits' : 'ideas wait'} until the current test ends`
            : 'New ideas come after the current test'
        : ready || scoutRunning
          ? null
          : goal.state.scout_reason
    const blocked = goal.is_owner && waitingIdeas.length > 0 && !ideaInProgress ? buildDisabledReason : null
    const listOpen = !ideaInProgress || laterOpen
    return (
        <div id="goal-ideas" className="scroll-mt-4">
            <SceneSection
                title={ready && !ideaInProgress ? 'Ideas that wait for you' : 'Ideas'}
                description={[summary, blocked].filter(Boolean).join(' ') || undefined}
                titleSize="sm"
                className="gap-y-2"
                actions={
                    <div className="flex flex-wrap items-center gap-2">
                        {ideaInProgress && (waitingIdeas.length > 0 || dismissedIdeas.length > 0) && (
                            <LemonButton
                                size="small"
                                type="tertiary"
                                onClick={() => setLaterOpen(!laterOpen)}
                                data-attr="goal-ideas-later"
                            >
                                {laterOpen ? 'Hide waiting ideas' : 'Show waiting ideas'}
                            </LemonButton>
                        )}
                        {canAdd && !addingIdea && (
                            <LemonButton
                                size="small"
                                type="tertiary"
                                icon={<IconPlus />}
                                disabledReason={busy ? 'Saving a change' : undefined}
                                onClick={() => setAddingIdea(true)}
                                data-attr="goal-add-idea"
                            >
                                Add an idea
                            </LemonButton>
                        )}
                    </div>
                }
            >
                {ideaError && (
                    <p role="alert" className="m-0 text-sm text-danger">
                        {ideaError}
                    </p>
                )}
                {addingIdea && <GoalAddIdeaForm goalId={goal.id} />}
                {scoutRunning && !ideaInProgress && (
                    <GoalRow
                        icon={<IconLightBulb className="size-4" />}
                        title={waitingIdeas.length ? 'Looking for more ideas' : 'Looking for ideas'}
                        facts={['The scout reads your data and code']}
                        actions={<Spinner className="size-4" />}
                        dataAttr="goal-scout-row"
                    />
                )}
                {listOpen && waitingIdeas.map((item) => <GoalIdeaRow key={item.id} item={item} goal={goal} />)}
                {listOpen && dismissedIdeas.length > 0 && (
                    <>
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            className="self-start"
                            onClick={() => setDismissedOpen(!dismissedOpen)}
                            data-attr="goal-ideas-dismissed"
                        >
                            {dismissedOpen ? 'Hide' : 'Show'} dismissed ideas ({dismissedIdeas.length})
                        </LemonButton>
                        {dismissedOpen &&
                            dismissedIdeas.map((item) => (
                                <GoalRow
                                    key={item.id}
                                    icon={<IconLightBulb className="size-4" />}
                                    title={item.title}
                                    tag={{ label: 'Dismissed', type: 'muted' }}
                                    facts={[item.dismissed_reason]}
                                    muted
                                    dataAttr="goal-idea-dismissed"
                                />
                            ))}
                    </>
                )}
                <GoalBuildModal goal={goal} />
            </SceneSection>
        </div>
    )
}

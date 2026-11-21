import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'

import posthog from 'lib/posthog-typed'
import { teamLogic } from 'scenes/teamLogic'

import { mcpEarlyDataLogic } from './mcpEarlyDataLogic'
import type { NextStep, NextStepKey } from './nextSteps'

export type ActivityCardKey = 'welcome' | NextStepKey

export const activityCardsLogic = kea([
    // pinned: the path names the localStorage key that holds dismissed cards
    path(['products', 'mcp_analytics', 'frontend', 'earlyData', 'activityCardsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId'], mcpEarlyDataLogic, ['nextSteps']],
    })),
    actions({
        dismissCard: (card: ActivityCardKey) => ({ card }),
        markDismissed: (teamId: string, card: ActivityCardKey) => ({ teamId, card }),
        showWelcomeThisVisit: true,
        showPreviousCard: true,
        showNextCard: true,
    }),
    reducers({
        // Per project, so setting something up in one project leaves the others' cards alone.
        dismissedByTeam: [
            {} as Record<string, ActivityCardKey[]>,
            { persist: true },
            {
                markDismissed: (state, { teamId, card }) =>
                    (state[teamId] ?? []).includes(card)
                        ? state
                        : { ...state, [teamId]: [...(state[teamId] ?? []), card] },
            },
        ],
        // The welcome is recorded as seen the moment it shows, and stays up for the rest of that visit.
        welcomeThisVisit: [
            false,
            {
                showWelcomeThisVisit: () => true,
                dismissCard: (state, { card }) => (card === 'welcome' ? false : state),
            },
        ],
        currentIndex: [
            0,
            {
                showPreviousCard: (index) => Math.max(0, index - 1),
                showNextCard: (index) => index + 1,
            },
        ],
    }),
    selectors({
        dismissed: [
            (s) => [s.dismissedByTeam, s.currentTeamId],
            (dismissedByTeam: Record<string, ActivityCardKey[]>, teamId: number | null): ActivityCardKey[] =>
                dismissedByTeam[String(teamId)] ?? [],
        ],
        cards: [
            (s) => [s.nextSteps, s.dismissed, s.welcomeThisVisit],
            (
                nextSteps: NextStep[] | null,
                dismissed: ActivityCardKey[],
                welcomeThisVisit: boolean
            ): ActivityCardKey[] => [
                ...(welcomeThisVisit ? (['welcome'] as ActivityCardKey[]) : []),
                ...(nextSteps ?? []).map((step) => step.key).filter((card) => !dismissed.includes(card)),
            ],
        ],
        // Stepping past the last card wraps to the first, and a dismissal keeps the place in the stack.
        currentCard: [
            (s) => [s.cards, s.currentIndex],
            (cards: ActivityCardKey[], currentIndex: number): ActivityCardKey | null =>
                cards.length > 0 ? cards[currentIndex % cards.length] : null,
        ],
    }),
    listeners(({ actions, values }) => ({
        dismissCard: ({ card }) => {
            posthog.capture('mcp analytics activity card dismissed', { card })
            actions.markDismissed(String(values.currentTeamId), card)
        },
    })),
    afterMount(({ actions, values }) => {
        if (!values.dismissed.includes('welcome')) {
            actions.showWelcomeThisVisit()
            actions.markDismissed(String(values.currentTeamId), 'welcome')
        }
    }),
])

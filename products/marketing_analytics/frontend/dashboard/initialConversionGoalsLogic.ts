import { MakeLogicType, actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'

import { teamLogic } from 'scenes/teamLogic'
import { marketingAnalyticsSettingsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsSettingsLogic'

import { ConversionGoalFilter } from '~/queries/schema/schema-general'

import {
    marketingAnalyticsConversionGoalsDeleteDestroy,
    marketingAnalyticsConversionGoalsInitializeCreate,
} from '../generated/api'

type InitialGoalProps = { teamId: number; canInitialize: boolean }

export const initialConversionGoalsLogic = kea<
    MakeLogicType<
        {
            goals: ConversionGoalFilter[]
            loading: boolean
            error: string | null
            initialized: boolean
            dismissed: boolean
            dismissedGoalIds: string[]
        },
        {
            dismiss: () => { value: true }
            expand: () => { value: true }
            dismissGoal: (goalId: string) => { goalId: string }
            load: () => { value: true }
            loaded: (
                goals: ConversionGoalFilter[],
                initialized: boolean
            ) => { goals: ConversionGoalFilter[]; initialized: boolean }
            failed: (error: string) => { error: string }
            removeGoal: (goalId: string) => { goalId: string }
            loadMarketingAnalyticsConfig: () => unknown
        },
        InitialGoalProps
    >
>([
    props({} as InitialGoalProps),
    key((props) => `${props.teamId}-${props.canInitialize}`),
    path((key) => ['products', 'marketingAnalytics', 'initialConversionGoals', key]),
    connect({ actions: [marketingAnalyticsSettingsLogic, ['loadMarketingAnalyticsConfig']] }),
    actions({
        dismiss: true,
        expand: true,
        dismissGoal: (goalId: string) => ({ goalId }),
        load: true,
        loaded: (goals: ConversionGoalFilter[], initialized: boolean) => ({ goals, initialized }),
        failed: (error: string) => ({ error }),
        removeGoal: (goalId: string) => ({ goalId }),
    }),
    reducers(({ props }) => ({
        dismissed: [
            false,
            { persist: true, prefix: `${props.teamId}__` },
            { dismiss: () => true, expand: () => false },
        ],
        dismissedGoalIds: [
            [] as string[],
            { persist: true, prefix: `${props.teamId}__` },
            { dismissGoal: (state, { goalId }) => [...new Set([...state, goalId])] },
        ],
        goals: [[] as ConversionGoalFilter[], { loaded: (_, { goals }) => goals }],
        initialized: [false, { loaded: (_, { initialized }) => initialized }],
        loading: [false, { load: () => true, removeGoal: () => true, loaded: () => false, failed: () => false }],
        error: [null as string | null, { load: () => null, removeGoal: () => null, failed: (_, { error }) => error }],
    })),
    listeners(({ actions, props }) => ({
        load: async () => {
            if (!props.canInitialize) {
                actions.loaded([], false)
                return
            }
            try {
                const result = await marketingAnalyticsConversionGoalsInitializeCreate(String(props.teamId))
                if (teamLogic.values.currentTeamId === props.teamId) {
                    await teamLogic.asyncActions.refreshCurrentTeam()
                    actions.loadMarketingAnalyticsConfig()
                }
                actions.loaded(result.initial_goals as ConversionGoalFilter[], result.initialized)
            } catch {
                actions.failed('Could not prepare conversion goals. Try again.')
            }
        },
        removeGoal: async ({ goalId }) => {
            try {
                await marketingAnalyticsConversionGoalsDeleteDestroy(String(props.teamId), goalId)
                actions.load()
            } catch {
                actions.failed('Could not delete this conversion goal. Try again.')
            }
        },
    })),
    afterMount(({ actions, props }) => {
        if (props.canInitialize) {
            actions.load()
        }
    }),
])

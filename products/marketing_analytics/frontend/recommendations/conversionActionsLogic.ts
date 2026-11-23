import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'
import {
    marketingAnalyticsSettingsLogic,
    marketingAnalyticsSettingsLogicActions,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsSettingsLogic'

import { performQuery } from '~/queries/query'
import {
    MarketingAnalyticsConversionActionsQuery,
    MarketingAnalyticsConversionActionsQueryResponse,
    NodeKind,
} from '~/queries/schema/schema-general'
import { TeamPublicType, TeamType } from '~/types'

import { ConversionActionAccount, conversionActionAccounts, sameConversionActions } from './conversionActions'
import { recommendationsLogic } from './recommendationsLogic'

export interface conversionActionsLogicValues {
    currentTeam: TeamType | TeamPublicType | null
    currentTeamLoading: boolean
    response: MarketingAnalyticsConversionActionsQueryResponse | null
    responseLoading: boolean
    loadFailed: boolean
    draft: string[] | null
    editorOpen: boolean
    savedActions: string[]
    selection: string[]
    accounts: ConversionActionAccount[]
    unmatchedActions: string[]
    changed: boolean
}

export interface conversionActionsLogicActions extends Pick<
    marketingAnalyticsSettingsLogicActions,
    'updateRecommendationConversionActions'
> {
    updateCurrentTeamSuccess: (
        currentTeam: TeamType | TeamPublicType,
        payload?: Partial<TeamType>
    ) => { currentTeam: TeamType | TeamPublicType; payload?: Partial<TeamType> }
    loadOptions: () => void
    loadOptionsSuccess: (response: MarketingAnalyticsConversionActionsQueryResponse | null) => {
        response: MarketingAnalyticsConversionActionsQueryResponse | null
    }
    loadOptionsFailure: (error: string) => { error: string }
    setSelection: (selection: string[]) => { selection: string[] }
    save: () => { value: true }
    openEditor: () => { value: true }
    closeEditor: () => { value: true }
}

export type conversionActionsLogicType = MakeLogicType<conversionActionsLogicValues, conversionActionsLogicActions>

export const conversionActionsLogic = kea<conversionActionsLogicType>([
    path(['products', 'marketingAnalytics', 'conversionActionsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam', 'currentTeamLoading']],
        actions: [
            marketingAnalyticsSettingsLogic,
            ['updateRecommendationConversionActions'],
            teamLogic,
            ['updateCurrentTeamSuccess'],
        ],
    })),
    actions({
        setSelection: (selection: string[]) => ({ selection }),
        save: true,
        openEditor: true,
        closeEditor: true,
    }),
    loaders({
        response: [
            null as MarketingAnalyticsConversionActionsQueryResponse | null,
            {
                loadOptions: async () =>
                    await performQuery<MarketingAnalyticsConversionActionsQuery>({
                        kind: NodeKind.MarketingAnalyticsConversionActionsQuery,
                    }),
            },
        ],
    }),
    reducers({
        loadFailed: [false, { loadOptionsSuccess: () => false, loadOptionsFailure: () => true }],
        draft: [
            null as string[] | null,
            {
                setSelection: (_, { selection }) => selection,
                closeEditor: () => null,
            },
        ],
        editorOpen: [false, { openEditor: () => true, closeEditor: () => false }],
    }),
    selectors({
        savedActions: [
            // The settings logic applies a change before the request succeeds, so the team is the saved state.
            (s) => [s.currentTeam],
            (currentTeam: TeamType | TeamPublicType | null): string[] =>
                (currentTeam && 'marketing_analytics_config' in currentTeam
                    ? currentTeam.marketing_analytics_config?.recommendation_conversion_actions
                    : null) ?? [],
        ],
        selection: [
            (s) => [s.draft, s.savedActions],
            (draft: string[] | null, savedActions: string[]): string[] => draft ?? savedActions,
        ],
        accounts: [
            (s) => [s.response, s.selection],
            (response: MarketingAnalyticsConversionActionsQueryResponse | null, selection: string[]) =>
                conversionActionAccounts(response?.results ?? [], selection),
        ],
        unmatchedActions: [
            (s) => [s.response, s.selection],
            (response: MarketingAnalyticsConversionActionsQueryResponse | null, selection: string[]): string[] =>
                (response?.unmatchedSavedActions ?? []).filter((action) => selection.includes(action)),
        ],
        changed: [
            (s) => [s.selection, s.savedActions],
            (selection: string[], savedActions: string[]): boolean => !sameConversionActions(selection, savedActions),
        ],
    }),
    listeners(({ actions, values }) => ({
        save: () => {
            actions.updateRecommendationConversionActions(values.selection)
        },
        updateCurrentTeamSuccess: ({ payload }) => {
            if (payload?.marketing_analytics_config?.recommendation_conversion_actions === undefined) {
                return
            }
            actions.closeEditor()
            // Saved actions that stopped converting are listed only once they are saved, and the recommendations
            // cache is keyed by the saved list, so both have to load again.
            actions.loadOptions()
            recommendationsLogic.findMounted()?.actions.loadData()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadOptions()
    }),
])

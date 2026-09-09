import { MakeLogicType, actions, kea, path, reducers } from 'kea'

import { DashboardSection, TrafficBreakdown } from './dashboardQueries'

export interface marketingDashboardLogicValues {
    includeConversionGoals: boolean
    section: DashboardSection
    breakdown: TrafficBreakdown
    revenueGoalId: string | null
}
export interface marketingDashboardLogicActions {
    setIncludeConversionGoals: (includeConversionGoals: boolean) => { includeConversionGoals: boolean }
    setSection: (section: DashboardSection) => { section: DashboardSection }
    setBreakdown: (breakdown: TrafficBreakdown) => { breakdown: TrafficBreakdown }
    setRevenueGoalId: (revenueGoalId: string) => { revenueGoalId: string }
}
export type marketingDashboardLogicType = MakeLogicType<marketingDashboardLogicValues, marketingDashboardLogicActions>

export const marketingDashboardLogic = kea<marketingDashboardLogicType>([
    path(['products', 'marketingAnalytics', 'marketingDashboardLogic']),
    actions({
        setIncludeConversionGoals: (includeConversionGoals: boolean) => ({ includeConversionGoals }),
        setSection: (section: DashboardSection) => ({ section }),
        setBreakdown: (breakdown: TrafficBreakdown) => ({ breakdown }),
        setRevenueGoalId: (revenueGoalId: string) => ({ revenueGoalId }),
    }),
    reducers({
        includeConversionGoals: [
            true,
            { setIncludeConversionGoals: (_, { includeConversionGoals }) => includeConversionGoals },
        ],
        section: ['acquisition' as DashboardSection, { setSection: (_, { section }) => section }],
        breakdown: ['$channel_type' as TrafficBreakdown, { setBreakdown: (_, { breakdown }) => breakdown }],
        revenueGoalId: [null as string | null, { setRevenueGoalId: (_, { revenueGoalId }) => revenueGoalId }],
    }),
])

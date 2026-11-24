import { useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { organizationLogic } from 'scenes/organizationLogic'

export function useNoDataAccess(): boolean {
    const { currentOrganization } = useValues(organizationLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const posthogAiV2 = useFeatureFlag('PHAI_SANDBOX_MODE')
    return todayRailNav && posthogAiV2 && currentOrganization?.ai_data_access === 'metadata_only'
}

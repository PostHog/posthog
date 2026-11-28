import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { readCachedHasData } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'

export function adventHasWorkflows(): boolean | null {
    const status = productSetupStatusLogic.findMounted({ productKey: ProductKey.WORKFLOWS })?.values.status
    if (status === 'needs-setup') {
        return false
    }
    return readCachedHasData(teamLogic.findMounted()?.values.currentTeamId ?? null, ProductKey.WORKFLOWS) || null
}

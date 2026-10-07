import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { findTestSendSkipReason } from './Workflows/hogflows/findTestSendSkipReason'
import type { HogflowTestResult } from './Workflows/hogflows/steps/types'

export function completeTestEmailSetupTask(result: HogflowTestResult | null): void {
    if (
        featureFlagLogic.findMounted()?.values.featureFlags[FEATURE_FLAGS.WORKFLOWS_FIRST_RUN] &&
        result?.status === 'success' &&
        !findTestSendSkipReason(result)
    ) {
        globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.SendWorkflowTestEmail)
    }
}

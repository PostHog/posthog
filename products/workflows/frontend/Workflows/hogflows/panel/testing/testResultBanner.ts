import { LemonBannerProps } from 'lib/lemon-ui/LemonBanner'

import { sandboxTestBanner, sandboxTestOutcome } from '../../steps/email/sandboxTestResult'
import { findTestSendSkipReason } from '../../steps/testSendSkipReason'
import { HogflowTestResult } from '../../steps/types'
import type { HogFlowAction } from '../../types'

export function testResultBanner(testResult: HogflowTestResult, actionType?: HogFlowAction['type']): LemonBannerProps {
    const sandboxOutcome = actionType === 'email_sandbox' ? sandboxTestOutcome(testResult) : null
    if (sandboxOutcome) {
        return sandboxTestBanner(sandboxOutcome)
    }
    const skipReason = findTestSendSkipReason(testResult)
    if (skipReason) {
        return { type: 'warning', children: skipReason }
    }
    if (testResult.status === 'skipped') {
        return { type: 'warning', children: 'Workflow was skipped because the event did not match the filter criteria' }
    }
    if (testResult.status === 'error') {
        return { type: 'error', children: 'Error: ' + testResult.errors?.join(', ') }
    }
    return { type: 'success', children: 'Success' }
}

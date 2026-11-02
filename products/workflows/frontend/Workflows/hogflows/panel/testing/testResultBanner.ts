import { findTestSendSkipReason } from '../../steps/testSendSkipReason'
import { HogflowTestResult } from '../../steps/types'

export interface TestResultBannerProps {
    type: 'success' | 'warning' | 'error'
    children: string
}

export function testResultBanner(testResult: HogflowTestResult): TestResultBannerProps {
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

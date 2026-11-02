import { HogflowTestResult } from './types'

export function findTestSendSkipReason(result: HogflowTestResult | null): string | undefined {
    const emailSendResult = result?.emailSendResult
    if (emailSendResult?.status !== 'skipped') {
        return undefined
    }
    return emailSendResult.reason || 'Nothing was sent to this recipient.'
}

import { HogflowTestResult } from './types'

// A declined send still finishes the step, so the run status reads `success` when nothing was sent.
export function findTestSendSkipReason(result: HogflowTestResult | null): string | undefined {
    const emailSendResult = result?.emailSendResult
    if (emailSendResult?.status !== 'skipped') {
        return undefined
    }
    return emailSendResult.reason || 'Nothing was sent to this recipient.'
}

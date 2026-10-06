import type { HogflowTestResult } from './steps/types'

// Every reason the email worker declines a send is logged behind this prefix
// (nodejs/src/cdp/services/messaging/email-validation.service.ts).
const SKIP_LOG_PREFIX = 'Skipping send:'

/**
 * The reason the worker declined to send, if it did.
 *
 * A declined send still finishes the step cleanly, so the invocation comes back `success` and the
 * reason appears only in the logs. Reading the status alone reports a test as delivered when
 * nothing was sent, and the sender waits for mail that never arrives.
 */
export function findTestSendSkipReason(result: HogflowTestResult | null): string | undefined {
    return result?.logs?.find((log) => log.message?.includes(SKIP_LOG_PREFIX))?.message
}

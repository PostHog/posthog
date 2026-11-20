import { UNIDENTIFIED_HARNESS_LABEL } from '../dashboard/harnessRegistry'
import type { MCPActivityRecentCallApi } from '../generated/api.schemas'

/** The name a call's client goes by, with the label `harnessMark` gives its own mark. */
export function callClientLabel(call: MCPActivityRecentCallApi): string {
    return call.client_name || UNIDENTIFIED_HARNESS_LABEL
}

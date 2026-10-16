import type { MCPActivityRecentCallApi } from '../generated/api.schemas'

/** The name a call's client goes by, with the label `harnessMark` gives its own mark. */
export function callClientLabel(call: MCPActivityRecentCallApi): string {
    return call.client_name || 'Unidentified client'
}

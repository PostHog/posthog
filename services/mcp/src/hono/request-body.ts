import { bodyTooLargeResponse, MAX_BODY_BYTES } from '@/lib/request-body'
import { redactToken } from '@/lib/utils'

import { requestBodyTooLargeTotal } from './metrics'

export function rejectBodyTooLarge(token: string | undefined): Response {
    requestBodyTooLargeTotal.inc()
    // A log alert matches this line, so keep its prefix stable. The token is cut to its last 4
    // characters, which traces a repeat sender without exposing the credential.
    console.warn(
        '[RequestBody] body too large',
        JSON.stringify({ maxBytes: MAX_BODY_BYTES, token: token ? redactToken(token) : null })
    )
    return bodyTooLargeResponse()
}

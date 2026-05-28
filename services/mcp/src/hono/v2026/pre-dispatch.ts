/**
 * v2026 pre-dispatch validation.
 *
 * Runs once per HTTP request before the dispatcher classifies the body.
 * Validates the SEP-2243 routing headers and the SEP-2575 per-request
 * `_meta` shape against the body. Throws `V2026ProtocolError` (caught by
 * the dispatcher and serialized as a JSON-RPC error) on any mismatch.
 *
 * Delegates to `parseV2026Meta` which already implements the rules — this
 * class is the thin adapter that the shared dispatcher calls via the
 * `PreDispatchStrategy` seam.
 */

import type { RequestProperties } from '@/lib/request-properties'

import type { PreDispatchStrategy } from '../protocol-strategy'
import { parseV2026Meta } from './request-meta'

export class V2026PreDispatch implements PreDispatchStrategy {
    async validate(req: Request, body: unknown, _props: RequestProperties): Promise<void> {
        // Reject non-object bodies up-front: `parseV2026Meta` expects a
        // JSON-RPC message shape.
        if (body === null || typeof body !== 'object' || Array.isArray(body)) {
            return
        }
        parseV2026Meta(req, body as Record<string, unknown>)
    }
}

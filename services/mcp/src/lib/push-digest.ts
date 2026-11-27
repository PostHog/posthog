import { createHash } from 'node:crypto'

import type { Schemas } from '@/api/generated'

const text = (value: unknown): string => (value === null || value === undefined ? '' : String(value))

/**
 * Hash of everything a person confirms about a push template. The API computes the same one under the template's
 * lock, in products/messaging/backend/services/push_digest.py, so both must change together.
 */
export function pushDigest(template: Schemas.MessageTemplate): string {
    const push = template.content?.push
    // By bytes, because the two languages order other strings differently.
    const data = Object.entries(push?.data ?? {}).sort(([a], [b]) => Buffer.compare(Buffer.from(a), Buffer.from(b)))
    return createHash('sha256')
        .update(
            JSON.stringify([
                'push-1',
                template.id,
                text(template.name),
                text(template.type),
                template.sensitive === true,
                text(push?.title),
                text(push?.body),
                text(push?.link),
                text(push?.image),
                data,
                (push?.channels ?? []).map(String),
                text(template.transactional_hog_flow_id),
            ])
        )
        .digest('hex')
}

import { Badge } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

export function QuillGatewayConnectionStatus({
    pendingOauth,
    needsReauth,
    accessRevoked,
    lastUsedAt,
}: {
    pendingOauth: boolean
    needsReauth: boolean
    accessRevoked: boolean
    lastUsedAt: string | null
}): JSX.Element {
    if (accessRevoked) {
        return <Badge>Access revoked</Badge>
    }

    if (needsReauth) {
        return <Badge variant="destructive">Needs reauth</Badge>
    }

    if (pendingOauth) {
        return <Badge variant="warning">Finishing setup</Badge>
    }

    return <Badge variant="success">{lastUsedAt ? `Used ${dayjs(lastUsedAt).fromNow()}` : 'Connected'}</Badge>
}

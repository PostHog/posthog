import type { AcpMessage, PendingPermission, PermissionRequestParams } from '../conversation/acp-types'
import { isJsonRpcNotification } from '../conversation/acp-types'
import { isNotification, POSTHOG_NOTIFICATIONS } from '../conversation/lib/acpExtensions'

function isValidRequestParams(params: unknown): params is PermissionRequestParams {
    if (!params || typeof params !== 'object') {
        return false
    }
    const p = params as Partial<PermissionRequestParams>
    return (
        typeof p.requestId === 'string' &&
        typeof p.toolCall?.toolCallId === 'string' &&
        Array.isArray(p.options) &&
        p.options.length > 0
    )
}

/**
 * Scan the ACP event stream for permission requests that are still awaiting a
 * user response. A request is pending until a matching
 * `_posthog/permission_resolved` notification arrives for the same `requestId`.
 * Returned in arrival order.
 */
export function derivePendingPermissions(events: AcpMessage[]): PendingPermission[] {
    const requests = new Map<string, PendingPermission>()
    const resolved = new Set<string>()

    for (const event of events) {
        const message = event.message
        if (!isJsonRpcNotification(message)) {
            continue
        }
        const params = message.params as { requestId?: string } | undefined
        if (typeof params?.requestId !== 'string') {
            continue
        }

        if (isNotification(message.method, POSTHOG_NOTIFICATIONS.PERMISSION_RESOLVED)) {
            resolved.add(params.requestId)
            requests.delete(params.requestId)
        } else if (
            isNotification(message.method, POSTHOG_NOTIFICATIONS.PERMISSION_REQUEST) &&
            isValidRequestParams(params)
        ) {
            if (!resolved.has(params.requestId)) {
                requests.set(params.requestId, { ...params, receivedAt: event.ts })
            }
        }
    }

    return Array.from(requests.values())
}

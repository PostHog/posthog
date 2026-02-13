import type { LemonTagType } from 'lib/lemon-ui/LemonTag/LemonTag'

import type { StatusCode } from '../data/mockTraceData'

export function statusTagType(status: StatusCode): LemonTagType {
    switch (status) {
        case 'ok':
            return 'success'
        case 'error':
            return 'danger'
        default:
            return 'muted'
    }
}

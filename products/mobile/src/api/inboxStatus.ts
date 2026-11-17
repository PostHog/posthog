import type { InboxStatusApi } from '../../../signals/frontend/generated/api.schemas'

import { apiJson, scopedPath } from './client'
import { type ProjectScope, reportKeys } from './reports'

export type { InboxStatusApi } from '../../../signals/frontend/generated/api.schemas'

export const inboxStatusKey = (scope: ProjectScope | null): readonly unknown[] => [...reportKeys.all(scope), 'status']

export function fetchInboxStatus(scope: ProjectScope, signal: AbortSignal): Promise<InboxStatusApi> {
    return apiJson<InboxStatusApi>(scopedPath(scope, 'signals/inbox_status/'), { signal })
}

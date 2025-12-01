import { kea, path } from 'kea'

import type { virtualizedLogsListLogicType } from './virtualizedLogsListLogicType'

export const virtualizedLogsListLogic = kea<virtualizedLogsListLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'VirtualizedLogsList', 'virtualizedLogsListLogic']),
])

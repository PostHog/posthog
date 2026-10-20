import type { LinkedDataKind } from '../../components/ExceptionCard/exceptionCardLogic'

export const LINKED_DATA_FILTER_LABELS: Record<LinkedDataKind, string> = {
    recording: 'Only with a recording',
    logs: 'Only with logs',
}

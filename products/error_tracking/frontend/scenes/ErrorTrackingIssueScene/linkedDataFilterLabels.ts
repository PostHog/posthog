import type { ErrorTrackingLinkedDataKind } from '~/queries/schema/schema-general'

export const LINKED_DATA_FILTER_LABELS: Record<ErrorTrackingLinkedDataKind, string> = {
    recording: 'Only with a recording',
    logs: 'Only with logs',
}

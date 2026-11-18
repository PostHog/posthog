import { Badge } from '@posthog/quill'

import { ExperimentConclusion, ExperimentStatus } from '~/types'

import { getExperimentStatusLabel } from 'products/experiments/frontend/scenes/experimentsLogic'

export type QuillBadgeVariant = 'default' | 'info' | 'warning' | 'success' | 'completed' | 'destructive'

export const EXPERIMENT_STATUS_BADGE: Record<ExperimentStatus, QuillBadgeVariant> = {
    [ExperimentStatus.Draft]: 'default',
    [ExperimentStatus.Running]: 'success',
    [ExperimentStatus.Paused]: 'warning',
    [ExperimentStatus.ExposureFrozen]: 'info',
    [ExperimentStatus.Stopped]: 'completed',
}

export const EXPERIMENT_CONCLUSION_DOT: Partial<Record<ExperimentConclusion, 'success' | 'destructive' | 'warning'>> = {
    [ExperimentConclusion.Won]: 'success',
    [ExperimentConclusion.Lost]: 'destructive',
    [ExperimentConclusion.Inconclusive]: 'warning',
}

export function QuillStatusBadge({ status }: { status: ExperimentStatus }): JSX.Element {
    return <Badge variant={EXPERIMENT_STATUS_BADGE[status]}>{getExperimentStatusLabel(status)}</Badge>
}

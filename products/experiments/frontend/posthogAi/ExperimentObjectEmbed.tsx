import { useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { experimentLogic } from '~/scenes/experiments/experimentLogic'

import type { ObjectEmbedProps } from 'products/posthog_ai/frontend/api/types'

import { NotebookExperimentComponent } from '../components/notebook'
import { StatusTag } from '../components/StatusTag'
import { getExperimentStatus } from '../experimentStatus'

function ExperimentHeader({ id }: { id: number }): JSX.Element {
    const { experiment, variants } = useValues(experimentLogic({ experimentId: id }))
    if (experiment?.id !== id) {
        return <LemonSkeleton className="h-6 w-48" />
    }
    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">{experiment.name}</span>
                <StatusTag status={getExperimentStatus(experiment)} />
            </div>
            {variants.length > 0 ? (
                <div className="flex flex-wrap items-center gap-1">
                    {variants.map((variant) => (
                        <LemonTag key={variant.key} type="muted">
                            {variant.key}
                            {variant.rollout_percentage != null ? ` ${variant.rollout_percentage}%` : ''}
                        </LemonTag>
                    ))}
                </div>
            ) : null}
        </div>
    )
}

/** A read-only experiment summary: status, variants and the most significant primary metric result. */
export function ExperimentObjectEmbed({ objectId }: ObjectEmbedProps): JSX.Element {
    const id = Number(objectId)
    if (!Number.isInteger(id) || id <= 0) {
        return <NotFound object="experiment" />
    }
    return (
        <div className="flex flex-col gap-2 p-4">
            <ExperimentHeader id={id} />
            <div className="rounded-md border border-primary bg-surface-primary">
                <NotebookExperimentComponent id={id} expanded />
            </div>
        </div>
    )
}

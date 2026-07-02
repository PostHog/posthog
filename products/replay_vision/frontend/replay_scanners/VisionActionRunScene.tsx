import { useValues } from 'kea'

import { LemonCard, LemonTable, LemonTableColumns, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import type { RunObservationApi } from '../generated/api.schemas'
import { visionActionRunSceneLogic } from './visionActionRunSceneLogic'
import { RunStatusTag } from './visionActionRunStatus'

export const scene: SceneExport = {
    component: VisionActionRunScene,
    logic: visionActionRunSceneLogic,
    productKey: ProductKey.REPLAY_VISION,
}

function RecordingsIncluded({ observations }: { observations: readonly RunObservationApi[] }): JSX.Element {
    const columns: LemonTableColumns<RunObservationApi> = [
        {
            title: 'Observation',
            key: 'observation',
            render: (_, obs) => (
                <Link
                    className="font-semibold truncate max-w-md inline-block align-bottom"
                    to={urls.replayVisionObservation(obs.id)}
                    title={obs.title || obs.session_id}
                >
                    {obs.title || obs.session_id}
                </Link>
            ),
        },
        {
            title: 'Person',
            key: 'person',
            render: (_, obs) => {
                const label = obs.recording_subject_email || obs.distinct_id
                if (!label) {
                    return (
                        <Tooltip title="No person is associated with this recording">
                            <span className="text-muted">No person</span>
                        </Tooltip>
                    )
                }
                // Without a distinct id we can't resolve a person page, so show the identifier as plain text.
                if (!obs.distinct_id) {
                    return (
                        <span className="truncate max-w-xs inline-block align-bottom" title={label}>
                            {label}
                        </span>
                    )
                }
                return (
                    <Link
                        className="truncate max-w-xs inline-block align-bottom"
                        to={urls.personByDistinctId(obs.distinct_id)}
                        title={label}
                    >
                        {label}
                    </Link>
                )
            },
        },
        {
            title: 'Time',
            key: 'time',
            render: (_, obs) => <TZLabel time={obs.created_at} formatDate="MMM D, YYYY" formatTime="HH:mm" />,
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            <h3 className="m-0">Recordings included: {observations.length}</h3>
            <LemonTable columns={columns} dataSource={[...observations]} rowKey="id" />
        </div>
    )
}

function VisionActionRunScene(): JSX.Element {
    const { run, runLoading } = useValues(visionActionRunSceneLogic)

    if (runLoading) {
        return (
            <SceneContent>
                <div className="flex justify-center p-8">
                    <Spinner className="text-2xl" />
                </div>
            </SceneContent>
        )
    }

    if (!run) {
        return (
            <SceneContent>
                <SceneTitleSection name="Run not found" resourceType={{ type: 'replay_vision' }} />
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Run summary"
                resourceType={{ type: 'replay_vision' }}
                actions={
                    <div className="flex items-center gap-2 text-sm text-secondary">
                        <RunStatusTag status={run.status} />
                        <TZLabel
                            time={run.scheduled_at ?? run.created_at}
                            formatDate="MMM D, YYYY"
                            formatTime="HH:mm"
                        />
                    </div>
                }
            />

            {run.synthesized_markdown ? (
                <LemonCard hoverEffect={false} className="p-4">
                    <LemonMarkdown className="text-base">{run.synthesized_markdown}</LemonMarkdown>
                </LemonCard>
            ) : run.status === 'running' ? (
                <div className="text-muted italic">This run is in progress — check back shortly for the summary.</div>
            ) : (
                <LemonBanner type={run.status === 'failed' ? 'error' : 'info'}>
                    <div className="font-semibold">
                        {run.status === 'failed'
                            ? 'This run failed'
                            : run.status === 'skipped'
                              ? 'This run was skipped'
                              : 'This run produced no summary'}
                    </div>
                    <div>{run.error_reason || 'No summary was produced for this run.'}</div>
                </LemonBanner>
            )}

            {run.observations.length > 0 ? (
                <RecordingsIncluded observations={run.observations} />
            ) : (
                run.synthesized_markdown && (
                    <div className="text-muted text-sm">
                        No recordings to show — they may predate this feature, or have since been deleted.
                    </div>
                )
            )}
        </SceneContent>
    )
}

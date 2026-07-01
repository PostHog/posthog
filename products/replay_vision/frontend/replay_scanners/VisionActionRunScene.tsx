import { useValues } from 'kea'

import { LemonTable, LemonTableColumns, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import type { RunObservationApi, VisionActionRunStatusEnumApi } from '../generated/api.schemas'
import { visionActionRunSceneLogic } from './visionActionRunSceneLogic'

export const scene: SceneExport = {
    component: VisionActionRunScene,
    logic: visionActionRunSceneLogic,
    productKey: ProductKey.REPLAY_VISION,
}

const STATUS_TAG: Record<
    VisionActionRunStatusEnumApi,
    { type: 'success' | 'danger' | 'warning' | 'primary'; label: string }
> = {
    completed: { type: 'success', label: 'Completed' },
    failed: { type: 'danger', label: 'Failed' },
    skipped: { type: 'warning', label: 'Skipped' },
    running: { type: 'primary', label: 'Running' },
}

function RecordingsIncluded({ observations }: { observations: readonly RunObservationApi[] }): JSX.Element {
    const columns: LemonTableColumns<RunObservationApi> = [
        {
            title: 'Recording',
            key: 'recording',
            render: (_, obs) => (
                <Link className="font-semibold" to={urls.replayVisionObservation(obs.id)}>
                    {obs.recording_subject_email || obs.session_id}
                </Link>
            ),
        },
        {
            title: 'What was observed',
            key: 'title',
            render: (_, obs) => <span className="text-sm">{obs.title || <span className="text-muted">—</span>}</span>,
        },
        {
            title: 'When',
            key: 'when',
            render: (_, obs) => <TZLabel time={obs.created_at} formatDate="MMM D, YYYY" formatTime="HH:mm" />,
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            <h3 className="m-0">Recordings included ({observations.length})</h3>
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

    const tag = STATUS_TAG[run.status]

    return (
        <SceneContent>
            <SceneTitleSection
                name="Run summary"
                resourceType={{ type: 'replay_vision' }}
                actions={
                    <div className="flex items-center gap-2 text-sm text-secondary">
                        <LemonTag type={tag.type} size="small">
                            {tag.label}
                        </LemonTag>
                        <TZLabel
                            time={run.scheduled_at ?? run.created_at}
                            formatDate="MMM D, YYYY"
                            formatTime="HH:mm"
                        />
                    </div>
                }
            />

            {run.synthesized_markdown ? (
                <LemonMarkdown className="text-base">{run.synthesized_markdown}</LemonMarkdown>
            ) : (
                <div className="text-muted italic">{run.error_reason || 'No summary was produced for this run.'}</div>
            )}

            {run.observations.length > 0 ? (
                <RecordingsIncluded observations={run.observations} />
            ) : (
                run.synthesized_markdown && (
                    <div className="text-muted text-sm">
                        The list of recordings wasn't recorded for this run (runs summarized before this feature shipped
                        don't have it).
                    </div>
                )
            )}
        </SceneContent>
    )
}

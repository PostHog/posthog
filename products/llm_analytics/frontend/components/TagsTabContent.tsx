import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import { generationTagRunsLogic } from '../generationTagRunsLogic'
import { TagRun } from '../tags/llmTaggerLogic'

export function TagsTabContent({ generationEventId }: { generationEventId: string }): JSX.Element {
    const logic = generationTagRunsLogic({ generationEventId })
    const { generationTagRuns, generationTagRunsLoading } = useValues(logic)
    const { loadGenerationTagRuns } = useActions(logic)

    const columns: LemonTableColumns<TagRun> = [
        {
            title: 'Tagger',
            key: 'tagger_name',
            render: (_, run) => <span className="font-medium">{run.tagger_name || '-'}</span>,
        },
        {
            title: 'Tags',
            key: 'tags',
            render: (_, run) => (
                <div className="flex flex-wrap gap-1">
                    {run.tags.length > 0 ? (
                        run.tags.map((tag: string) => (
                            <LemonTag key={tag} type="highlight">
                                {tag}
                            </LemonTag>
                        ))
                    ) : (
                        <span className="text-muted text-sm">No tags</span>
                    )}
                </div>
            ),
        },
        {
            title: 'Reasoning',
            key: 'reasoning',
            render: (_, run) =>
                run.reasoning ? (
                    <Tooltip title={run.reasoning} placement="top">
                        <div className="max-w-md text-sm truncate cursor-default">{run.reasoning}</div>
                    </Tooltip>
                ) : (
                    <span className="text-muted text-sm">-</span>
                ),
        },
        {
            title: 'Timestamp',
            key: 'timestamp',
            render: (_, run) => <TZLabel time={run.timestamp} />,
        },
    ]

    return (
        <div className="py-4">
            <div className="flex justify-between items-center mb-4">
                <p className="text-muted text-sm m-0">Tags applied to this generation by your taggers.</p>
                <LemonButton
                    type="secondary"
                    icon={<IconRefresh />}
                    onClick={loadGenerationTagRuns}
                    loading={generationTagRunsLoading}
                    size="small"
                >
                    Refresh
                </LemonButton>
            </div>
            <LemonTable
                columns={columns}
                dataSource={generationTagRuns}
                loading={generationTagRunsLoading}
                rowKey="timestamp"
                nouns={['tag run', 'tag runs']}
                emptyState={
                    <div className="text-center py-8 text-muted">
                        No tags applied to this generation yet.{' '}
                        <Link to={urls.llmAnalyticsTags()}>Enable a tagger</Link> to start tagging.
                    </div>
                }
            />
        </div>
    )
}

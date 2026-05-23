import { useValues } from 'kea'

import { LemonSkeleton, LemonTable } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { Mention, socialSignalsLogic } from '../logics/socialSignalsLogic'

export const scene: SceneExport = {
    component: SocialSignalsScene,
    logic: socialSignalsLogic,
}

export function SocialSignalsScene(): JSX.Element {
    const { mentions, mentionsLoading } = useValues(socialSignalsLogic)

    return (
        <SceneContent>
            <SceneTitleSection name="Social signals" resourceType={{ type: 'social_signals' }} />
            {mentionsLoading && mentions.length === 0 ? (
                <LemonSkeleton className="h-32 w-full max-w-2xl" />
            ) : (
                <LemonTable<Mention>
                    dataSource={mentions}
                    rowKey="id"
                    emptyState="No mentions yet. Configure a source in Settings to start ingesting."
                    columns={[
                        {
                            title: 'Platform',
                            dataIndex: 'platform',
                            width: 120,
                        },
                        {
                            title: 'Author',
                            dataIndex: 'author_handle',
                            width: 180,
                            render: (_, m) => m.author_display_name || m.author_handle || '—',
                        },
                        {
                            title: 'Content',
                            dataIndex: 'content',
                            render: (_, m) => (
                                <span className="line-clamp-2 text-sm">{m.content || '(empty)'}</span>
                            ),
                        },
                        {
                            title: 'Status',
                            dataIndex: 'status',
                            width: 110,
                        },
                        {
                            title: 'Captured',
                            dataIndex: 'captured_at',
                            width: 180,
                            render: (_, m) => new Date(m.captured_at).toLocaleString(),
                        },
                    ]}
                />
            )}
        </SceneContent>
    )
}

export default SocialSignalsScene

import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { contentAutopilotPromptDetailLogic } from './contentAutopilotPromptDetailLogic'

export const ContentAutopilotPromptVersions = ({ promptId }: { promptId: string }): JSX.Element => {
    const { versions, versionsLoading, versionsFailed } = useValues(contentAutopilotPromptDetailLogic)
    const { loadAeoPromptVersions } = useActions(contentAutopilotPromptDetailLogic)

    if (versionsFailed && !versions) {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: () => loadAeoPromptVersions(promptId) }}
            >
                Couldn't load the versions of this prompt. Try again, and if it keeps happening contact support.
            </LemonBanner>
        )
    }

    if (!versions) {
        return <LemonSkeleton className="h-24 w-full" />
    }

    return (
        <LemonTable
            size="small"
            dataSource={versions}
            rowKey="version"
            loading={versionsLoading}
            columns={[
                {
                    title: 'Version',
                    key: 'version',
                    render: (_, { version, is_current }) => (
                        <div className="flex items-center gap-2 whitespace-nowrap">
                            <span>{version}</span>
                            {is_current ? (
                                <LemonTag type="success" size="small">
                                    Current
                                </LemonTag>
                            ) : null}
                        </div>
                    ),
                },
                {
                    title: 'Text',
                    key: 'text',
                    render: (_, { text, version_description }) => (
                        <div className="py-1 min-w-60 break-words">
                            <div>{text}</div>
                            {version_description ? (
                                <div className="text-muted text-xs mt-1">{version_description}</div>
                            ) : null}
                        </div>
                    ),
                },
                {
                    title: 'Changed by',
                    key: 'created_by',
                    render: (_, { created_by }) =>
                        created_by ? (
                            <span className="whitespace-nowrap">{created_by.name || created_by.email}</span>
                        ) : (
                            <span className="text-muted whitespace-nowrap">Unknown</span>
                        ),
                },
                {
                    title: 'Created',
                    key: 'created_at',
                    render: (_, { created_at }) => <TZLabel time={created_at} className="whitespace-nowrap" />,
                },
            ]}
        />
    )
}

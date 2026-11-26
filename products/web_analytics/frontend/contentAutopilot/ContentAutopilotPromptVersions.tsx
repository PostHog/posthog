import { useActions, useValues } from 'kea'

import { Skeleton, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import { AiVisibilityBanner } from './AiVisibilityBanner'
import { AiVisibilityTable } from './AiVisibilityTable'
import { AiVisibilityTag } from './AiVisibilityTag'
import { contentAutopilotPromptDetailLogic } from './contentAutopilotPromptDetailLogic'

export const ContentAutopilotPromptVersions = ({ promptId }: { promptId: string }): JSX.Element => {
    const { versions, versionsLoading, versionsFailed } = useValues(contentAutopilotPromptDetailLogic)
    const { loadAeoPromptVersions } = useActions(contentAutopilotPromptDetailLogic)

    const errorBanner = (
        <AiVisibilityBanner
            type="error"
            action={{ children: 'Try again', onClick: () => loadAeoPromptVersions(promptId) }}
        >
            Couldn't load the versions of this prompt. Try again, and if it keeps happening contact support.
        </AiVisibilityBanner>
    )

    if (versionsFailed && !versions) {
        return errorBanner
    }

    if (!versions) {
        return <Skeleton className="h-24 w-full" />
    }

    // A reload after an edit can fail while the older list is still shown, so the error sits above it.
    return (
        <div className="flex flex-col gap-2">
            {versionsFailed ? errorBanner : null}
            <AiVisibilityTable
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
                                {is_current ? <AiVisibilityTag type="success">Current</AiVisibilityTag> : null}
                            </div>
                        ),
                    },
                    {
                        title: 'Text',
                        key: 'text',
                        render: (_, { text, version_description }) => (
                            <div className="flex min-w-60 flex-col gap-1 py-1 break-words">
                                <div>{text}</div>
                                {version_description ? (
                                    <Text size="xs" variant="muted" className="m-0">
                                        {version_description}
                                    </Text>
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
                                <span className="text-muted-foreground whitespace-nowrap">Unknown</span>
                            ),
                    },
                    {
                        title: 'Created',
                        key: 'created_at',
                        render: (_, { created_at }) => <TZLabel time={created_at} className="whitespace-nowrap" />,
                    },
                ]}
            />
        </div>
    )
}

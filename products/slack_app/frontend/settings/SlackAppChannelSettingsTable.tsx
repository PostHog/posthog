import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { slackIntegrationLogic } from 'lib/integrations/slackIntegrationLogic'

import type { IntegrationType } from '~/types'

import type { SlackAppChannelSettingsApi, SlackUntaggedModeEnumApi } from '../generated/api.schemas'
import { slackAppSettingsLogic } from './slackAppSettingsLogic'

const INHERIT = 'inherit'

const QUESTION_MODE_OPTIONS: { value: SlackUntaggedModeEnumApi | typeof INHERIT; label: string }[] = [
    { value: INHERIT, label: "Each person's setting" },
    { value: 'auto', label: 'Answer automatically' },
    { value: 'ask', label: 'Ask first' },
    { value: 'never', label: 'Never' },
]

const CLEARED = { default_integration_id: null, default_repository: null, untagged_question_mode: null }

function RepositoryInput({
    value,
    onSave,
}: {
    value: string | null
    onSave: (repository: string | null) => void
}): JSX.Element {
    const [draft, setDraft] = useState(value ?? '')
    const save = (): void => {
        const repository = draft.trim() || null
        if (repository !== value) {
            onSave(repository)
        }
    }
    return (
        <LemonInput
            className="w-48"
            size="small"
            placeholder="owner/repo"
            value={draft}
            onChange={setDraft}
            onBlur={save}
            onPressEnter={save}
            data-attr="slack-app-channel-settings-repository"
        />
    )
}

export function SlackAppChannelSettingsTable({ integration }: { integration: IntegrationType }): JSX.Element {
    const { settings, channelRows } = useValues(slackAppSettingsLogic)
    const { saveChannel } = useActions(slackAppSettingsLogic)
    const { slackChannels } = useValues(slackIntegrationLogic({ id: integration.id }))

    const projectOptions = [
        { value: INHERIT, label: "Each person's default" },
        ...(settings?.personal.project_options ?? []).map((option) => ({
            value: String(option.integration_id),
            label: option.project_name,
        })),
    ]

    const save = (row: SlackAppChannelSettingsApi, change: Partial<SlackAppChannelSettingsApi>): void =>
        saveChannel({
            slackChannelId: row.slack_channel_id,
            change: {
                default_integration_id: row.default_integration_id,
                default_repository: row.default_repository,
                untagged_question_mode: row.untagged_question_mode,
                ...change,
            },
        })

    return (
        <LemonTable
            dataSource={channelRows}
            rowKey="slack_channel_id"
            emptyState="No channel has its own settings yet. Add a channel to give it a default project, repository or question mode."
            columns={[
                {
                    title: 'Channel',
                    key: 'channel',
                    render: (_, row) => {
                        const channel = slackChannels.find((c) => c.id === row.slack_channel_id)
                        return (
                            <div className="py-1">
                                <div className="flex items-center gap-1 font-semibold">
                                    {channel?.is_private ? '🔒' : '#'}
                                    {channel?.name ?? row.slack_channel_id}
                                    {channel?.is_ext_shared ? <LemonTag size="small">Shared</LemonTag> : null}
                                </div>
                                {row.updated_by_name && row.updated_at ? (
                                    <div className="text-secondary text-xs">
                                        Changed by {row.updated_by_name} <TZLabel time={row.updated_at} />
                                    </div>
                                ) : null}
                            </div>
                        )
                    },
                },
                {
                    title: 'Default project',
                    key: 'project',
                    render: (_, row) => (
                        <LemonSelect
                            className="w-48"
                            size="small"
                            value={row.default_integration_id ? String(row.default_integration_id) : INHERIT}
                            onChange={(value) =>
                                save(row, { default_integration_id: value === INHERIT ? null : Number(value) })
                            }
                            options={projectOptions}
                            data-attr="slack-app-channel-settings-project"
                        />
                    ),
                },
                {
                    title: 'Default repository',
                    key: 'repository',
                    render: (_, row) => (
                        <RepositoryInput
                            value={row.default_repository}
                            onSave={(repository) => save(row, { default_repository: repository })}
                        />
                    ),
                },
                {
                    title: 'Questions without a tag',
                    key: 'questions',
                    render: (_, row) => (
                        <LemonSelect
                            className="w-48"
                            size="small"
                            value={row.untagged_question_mode ?? INHERIT}
                            onChange={(value) =>
                                save(row, { untagged_question_mode: value === INHERIT ? null : value })
                            }
                            options={QUESTION_MODE_OPTIONS}
                            data-attr="slack-app-channel-settings-questions"
                        />
                    ),
                },
                {
                    key: 'remove',
                    width: 0,
                    render: (_, row) => (
                        <LemonButton
                            size="small"
                            icon={<IconTrash />}
                            status="danger"
                            tooltip="Remove this channel's settings"
                            onClick={() => saveChannel({ slackChannelId: row.slack_channel_id, change: CLEARED })}
                            data-attr="slack-app-channel-settings-remove"
                        />
                    ),
                },
            ]}
        />
    )
}

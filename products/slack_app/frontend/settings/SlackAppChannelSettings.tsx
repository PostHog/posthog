import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonInput, LemonSelect, LemonSkeleton, LemonTable } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { SlackAppChannelSettingsApi, SlackUntaggedModeEnumApi } from '../generated/api.schemas'
import { SlackAppInstallPicker } from './SlackAppInstallPicker'
import { slackAppSettingsLogic } from './slackAppSettingsLogic'

const INHERIT = 'inherit'

const QUESTION_MODE_OPTIONS: { value: SlackUntaggedModeEnumApi | typeof INHERIT; label: string }[] = [
    { value: INHERIT, label: "Use each person's setting" },
    { value: 'auto', label: 'Answer automatically' },
    { value: 'ask', label: 'Ask first' },
    { value: 'never', label: 'Never' },
]

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
            size="small"
            placeholder="Choose automatically"
            value={draft}
            onChange={setDraft}
            onBlur={save}
            onPressEnter={save}
            data-attr="slack-app-channel-settings-repository"
        />
    )
}

export function SlackAppChannelSettings(): JSX.Element | null {
    const { settings, channelRows, channelNames, channelOptions, channelsLoading, slackIntegrations } =
        useValues(slackAppSettingsLogic)
    const { saveChannel, addChannel } = useActions(slackAppSettingsLogic)

    if (!slackIntegrations?.length) {
        return null
    }
    if (channelsLoading && channelRows.length === 0) {
        return <LemonSkeleton className="h-40" />
    }

    const projectOptions = [
        { value: INHERIT, label: "Use each person's default" },
        ...(settings?.personal.project_options ?? []).map((option) => ({
            value: String(option.integration_id),
            label: option.project_name,
        })),
    ]
    const shownIds = new Set(channelRows.map((row) => row.slack_channel_id))
    const addableChannels = (channelOptions ?? []).filter((option) => !shownIds.has(option.id))

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
        <div className="flex flex-col gap-2">
            <SlackAppInstallPicker />
            <div className="flex justify-end">
                <LemonSelect
                    placeholder="Add channel"
                    value={null}
                    onChange={(channelId) => channelId && addChannel(channelId)}
                    options={addableChannels.map((option) => ({ value: option.id, label: `#${option.name}` }))}
                    disabledReason={
                        addableChannels.length === 0 ? 'PostHog found no other public channels.' : undefined
                    }
                    data-attr="slack-app-channel-settings-add"
                />
            </div>
            <LemonTable
                dataSource={channelRows}
                rowKey="slack_channel_id"
                emptyState="No channel has its own settings. Add a channel to set them."
                columns={[
                    {
                        title: 'Channel',
                        key: 'channel',
                        render: (_, row) => (
                            <div>
                                <div className="font-semibold">
                                    #{channelNames[row.slack_channel_id] ?? row.slack_channel_id}
                                </div>
                                {row.updated_by_name && row.updated_at ? (
                                    <div className="text-secondary text-xs">
                                        Changed by {row.updated_by_name} <TZLabel time={row.updated_at} />
                                    </div>
                                ) : null}
                            </div>
                        ),
                    },
                    {
                        title: 'Default project',
                        key: 'project',
                        render: (_, row) => (
                            <LemonSelect
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
                                type="secondary"
                                onClick={() =>
                                    saveChannel({
                                        slackChannelId: row.slack_channel_id,
                                        change: {
                                            default_integration_id: null,
                                            default_repository: null,
                                            untagged_question_mode: null,
                                        },
                                    })
                                }
                                data-attr="slack-app-channel-settings-remove"
                            >
                                Remove
                            </LemonButton>
                        ),
                    },
                ]}
            />
        </div>
    )
}

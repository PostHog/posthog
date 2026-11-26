import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { LemonSearchableSelect, LemonSelect, Link } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { urls } from 'scenes/urls'

import type { IntegrationType } from '~/types'

import type { SlackChannelQuestionModeEnumApi } from '../generated/api.schemas'
import { ChannelDraft, slackAppSettingsLogic } from './slackAppSettingsLogic'
import { SlackChannelSelect } from './SlackChannelSelect'

const INHERIT = 'inherit'

const QUESTION_MODE_OPTIONS: { value: SlackChannelQuestionModeEnumApi | typeof INHERIT; label: string }[] = [
    { value: INHERIT, label: "Use each person's setting" },
    { value: 'ask', label: 'Ask first' },
    { value: 'never', label: 'Only answer @-mentions' },
]

function RepositoryField({
    value,
    onChange,
}: {
    value: string | null
    onChange: (repository: string | null) => void
}): JSX.Element {
    const { repositoryOptions, repositoryOptionsLoading } = useValues(slackAppSettingsLogic)

    if (repositoryOptions && !repositoryOptions.github_connected) {
        return (
            <p className="text-secondary text-sm m-0">
                <Link to={urls.settings('user-personal-integrations', 'personal-integrations-github')}>
                    Connect your GitHub account
                </Link>{' '}
                to pick a repository for this channel.
            </p>
        )
    }

    const repositories = repositoryOptions?.repositories ?? []
    const options = [
        { value: INHERIT, label: 'Choose automatically' },
        ...(value && !repositories.includes(value) ? [value] : []).concat(repositories).map((repository) => ({
            value: repository,
            label: repository,
            icon: <IconGithub />,
        })),
    ]

    return (
        <LemonSearchableSelect
            fullWidth
            value={value ?? INHERIT}
            onChange={(repository) => onChange(repository === INHERIT || !repository ? null : repository)}
            options={options}
            loading={repositoryOptionsLoading}
            searchPlaceholder="Search repositories"
            noResultsMessage="No repository matches"
            searchInputDataAttr="slack-app-channel-settings-repository-search"
            menu={{ className: '!max-h-80' }}
            data-attr="slack-app-channel-settings-repository"
        />
    )
}

export function SlackAppChannelSettingsForm({
    integration,
    draft,
}: {
    integration: IntegrationType
    draft: ChannelDraft
}): JSX.Element {
    const { isEditingChannel, settings } = useValues(slackAppSettingsLogic)
    const { setChannelDraft } = useActions(slackAppSettingsLogic)

    return (
        <div className="flex flex-col gap-4">
            {!isEditingChannel ? (
                <LemonField.Pure label="Channel">
                    <SlackChannelSelect
                        integration={integration}
                        value={draft.slack_channel_id}
                        onChange={(slackChannelId) => setChannelDraft({ slack_channel_id: slackChannelId })}
                    />
                </LemonField.Pure>
            ) : null}
            <LemonField.Pure label="Default project" help="The project PostHog uses when someone tags it here.">
                <LemonSelect
                    fullWidth
                    value={draft.default_integration_id ?? INHERIT}
                    onChange={(value) =>
                        setChannelDraft({ default_integration_id: value === INHERIT ? null : Number(value) })
                    }
                    options={[
                        { value: INHERIT, label: "Use each person's default" },
                        ...(settings?.personal.project_options ?? []).map((option) => ({
                            value: option.integration_id,
                            label: option.project_name,
                        })),
                    ]}
                    data-attr="slack-app-channel-settings-project"
                />
            </LemonField.Pure>
            <LemonField.Pure
                label="Default repository"
                help="Tasks started here use this repository when nobody names one. People without access to it get the usual choice."
            >
                <RepositoryField
                    value={draft.default_repository}
                    onChange={(repository) => setChannelDraft({ default_repository: repository })}
                />
            </LemonField.Pure>
            <LemonField.Pure
                label="Questions without a tag"
                help="What PostHog does with a question in this channel that doesn't tag it. A channel can only make this stricter than each person's own setting."
            >
                <LemonSelect
                    fullWidth
                    value={draft.untagged_question_mode ?? INHERIT}
                    onChange={(value) => setChannelDraft({ untagged_question_mode: value === INHERIT ? null : value })}
                    options={QUESTION_MODE_OPTIONS}
                    data-attr="slack-app-channel-settings-questions"
                />
            </LemonField.Pure>
        </div>
    )
}

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, Link } from '@posthog/lemon-ui'

import api from 'lib/api'
import { GitHubRepositoryPicker } from 'lib/integrations/GitHubIntegrationHelpers'
import { LinearTeamPicker } from 'lib/integrations/LinearIntegrationHelpers'
import { SlackChannelPicker } from 'lib/integrations/SlackIntegrationHelpers'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'

import { IntegrationType } from '~/types'

import {
    DestinationOption,
    TRIGGER_OPTIONS,
    TriggerOption,
    errorTrackingAlertWizardLogic,
} from './errorTrackingAlertWizardLogic'

function WizardCard({
    icon,
    name,
    description,
    onClick,
}: {
    icon?: React.ReactNode
    name: string
    description: string
    onClick: () => void
}): JSX.Element {
    return (
        <button
            type="button"
            onClick={onClick}
            className={clsx(
                'group relative text-left rounded-lg border border-border bg-bg-light transition-all cursor-pointer p-5 w-full',
                'hover:border-border-bold hover:shadow-sm',
                'focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2'
            )}
        >
            <div className="flex items-center gap-4">
                {icon && <div className="shrink-0">{icon}</div>}
                <div>
                    <h3 className="font-semibold text-base mb-0.5 transition-colors group-hover:text-link">{name}</h3>
                    <p className="text-secondary text-sm mb-0">{description}</p>
                </div>
            </div>
        </button>
    )
}

function DestinationStep({ onBack }: { onBack: () => void }): JSX.Element {
    const { destinationOptions, existingAlertsLoading } = useValues(errorTrackingAlertWizardLogic)
    const { setDestination } = useActions(errorTrackingAlertWizardLogic)

    if (existingAlertsLoading) {
        return (
            <div className="space-y-4">
                <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} onClick={onBack}>
                    Alerts list
                </LemonButton>
                <h2 className="text-xl font-semibold">Where should we send alerts?</h2>
                <div className="space-y-3">
                    {[1, 2, 3].map((i) => (
                        <div key={i} className="h-20 rounded-lg border border-border bg-bg-light animate-pulse" />
                    ))}
                </div>
            </div>
        )
    }

    return (
        <div className="space-y-4">
            <div>
                <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} onClick={onBack}>
                    Alerts list
                </LemonButton>
                <h2 className="text-xl font-semibold mb-1 mt-2">Where should we send alerts?</h2>
                <p className="text-secondary text-sm">Choose your preferred notification channel</p>
            </div>
            <div className="space-y-3">
                {destinationOptions.map((option: DestinationOption) => (
                    <WizardCard
                        key={option.key}
                        icon={<HogFunctionIcon src={option.icon} size="medium" />}
                        name={option.name}
                        description={option.description}
                        onClick={() => setDestination(option.key)}
                    />
                ))}
            </div>
        </div>
    )
}

function TriggerStep(): JSX.Element {
    const { setTrigger, setStep } = useActions(errorTrackingAlertWizardLogic)

    return (
        <div className="space-y-4">
            <div>
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconArrowLeft />}
                    onClick={() => setStep('destination')}
                >
                    Choose destination
                </LemonButton>
                <h2 className="text-xl font-semibold mb-1 mt-2">What should trigger the alert?</h2>
                <p className="text-secondary text-sm">Choose when you want to be notified</p>
            </div>
            <div className="space-y-3">
                {TRIGGER_OPTIONS.map((option: TriggerOption) => (
                    <WizardCard
                        key={option.key}
                        name={option.name}
                        description={option.description}
                        onClick={() => setTrigger(option.key)}
                    />
                ))}
            </div>
        </div>
    )
}

function ConfigureStep(): JSX.Element {
    const {
        selectedDestination,
        slackIntegrations,
        slackAvailable,
        githubIntegrations,
        linearIntegrations,
        isConfigFormSubmitting,
        configForm,
    } = useValues(errorTrackingAlertWizardLogic)
    const { setStep } = useActions(errorTrackingAlertWizardLogic)

    const selectedSlackIntegration = (slackIntegrations || []).find(
        (i: IntegrationType) => i.id === configForm.slackWorkspaceId
    )
    const selectedGithubIntegration = githubIntegrations.find(
        (i: IntegrationType) => i.id === configForm.githubIntegrationId
    )
    const selectedLinearIntegration = linearIntegrations.find(
        (i: IntegrationType) => i.id === configForm.linearIntegrationId
    )

    return (
        <div className="space-y-4">
            <div>
                <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} onClick={() => setStep('trigger')}>
                    Choose trigger
                </LemonButton>
                <h2 className="text-xl font-semibold mb-1 mt-2">Configure your alert</h2>
                <p className="text-secondary text-sm">Fill in the details to complete setup</p>
            </div>

            <Form logic={errorTrackingAlertWizardLogic} formKey="configForm" enableFormOnSubmit className="space-y-4">
                {selectedDestination === 'slack' && (
                    <SlackConfigFields
                        slackIntegrations={slackIntegrations}
                        slackAvailable={slackAvailable}
                        selectedSlackIntegration={selectedSlackIntegration}
                    />
                )}
                {selectedDestination === 'discord' && <DiscordConfigFields />}
                {selectedDestination === 'microsoft-teams' && <TeamsConfigFields />}
                {selectedDestination === 'github' && (
                    <GitHubConfigFields
                        githubIntegrations={githubIntegrations}
                        selectedIntegration={selectedGithubIntegration}
                    />
                )}
                {selectedDestination === 'linear' && (
                    <LinearConfigFields
                        linearIntegrations={linearIntegrations}
                        selectedIntegration={selectedLinearIntegration}
                    />
                )}

                <div className="flex justify-end">
                    <LemonButton type="primary" htmlType="submit" loading={isConfigFormSubmitting}>
                        Create alert
                    </LemonButton>
                </div>
            </Form>
        </div>
    )
}

function SlackConfigFields({
    slackIntegrations,
    slackAvailable,
    selectedSlackIntegration,
}: {
    slackIntegrations: IntegrationType[] | undefined
    slackAvailable: boolean | undefined
    selectedSlackIntegration: IntegrationType | undefined
}): JSX.Element | null {
    if (!slackAvailable) {
        return (
            <div className="rounded-lg border border-border p-4 text-secondary text-sm">
                Slack is not configured for this project.{' '}
                <Link
                    to={api.integrations.authorizeUrl({
                        kind: 'slack',
                        next: window.location.pathname + window.location.search,
                    })}
                    disableClientSideRouting
                >
                    Connect Slack
                </Link>
            </div>
        )
    }

    if (!slackIntegrations || slackIntegrations.length === 0) {
        return (
            <div className="rounded-lg border border-border p-4 text-secondary text-sm">
                No Slack workspaces connected.{' '}
                <Link
                    to={api.integrations.authorizeUrl({
                        kind: 'slack',
                        next: window.location.pathname + window.location.search,
                    })}
                    disableClientSideRouting
                >
                    Connect Slack
                </Link>
            </div>
        )
    }

    return (
        <>
            <LemonField name="slackWorkspaceId" label="Workspace">
                <LemonSelect
                    options={slackIntegrations.map((integration) => ({
                        label: integration.display_name,
                        value: integration.id,
                    }))}
                />
            </LemonField>
            {selectedSlackIntegration && (
                <LemonField name="slackChannelId" label="Channel">
                    {({ value, onChange }) => (
                        <SlackChannelPicker value={value} onChange={onChange} integration={selectedSlackIntegration} />
                    )}
                </LemonField>
            )}
        </>
    )
}

function DiscordConfigFields(): JSX.Element {
    return (
        <LemonField
            name="discordWebhookUrl"
            label="Webhook URL"
            help={
                <span className="text-secondary text-xs">
                    Learn how to create a webhook:{' '}
                    <Link to="https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks">
                        Discord webhooks guide
                    </Link>
                </span>
            }
        >
            <LemonInput placeholder="https://discord.com/api/webhooks/..." />
        </LemonField>
    )
}

function TeamsConfigFields(): JSX.Element {
    return (
        <LemonField
            name="microsoftTeamsWebhookUrl"
            label="Webhook URL"
            help={
                <span className="text-secondary text-xs">
                    Learn how to create a webhook:{' '}
                    <Link to="https://support.microsoft.com/en-us/office/create-incoming-webhooks-with-workflows-for-microsoft-teams-8ae491c7-0394-4861-ba59-055e33f75498">
                        Microsoft Teams webhooks guide
                    </Link>
                </span>
            }
        >
            <LemonInput placeholder="https://outlook.office.com/webhook/..." />
        </LemonField>
    )
}

function GitHubConfigFields({
    githubIntegrations,
    selectedIntegration,
}: {
    githubIntegrations: IntegrationType[]
    selectedIntegration: IntegrationType | undefined
}): JSX.Element {
    if (githubIntegrations.length === 0) {
        return (
            <div className="rounded-lg border border-border p-4 text-secondary text-sm">
                No GitHub integrations connected.{' '}
                <Link
                    to={api.integrations.authorizeUrl({
                        kind: 'github',
                        next: window.location.pathname + window.location.search,
                    })}
                    disableClientSideRouting
                >
                    Connect GitHub
                </Link>
            </div>
        )
    }

    return (
        <>
            <LemonField name="githubIntegrationId" label="GitHub connection">
                <LemonSelect
                    options={githubIntegrations.map((integration) => ({
                        label: integration.display_name,
                        value: integration.id,
                    }))}
                />
            </LemonField>
            {selectedIntegration && (
                <LemonField name="githubRepository" label="Repository">
                    {({ value, onChange }) => (
                        <GitHubRepositoryPicker
                            value={value}
                            onChange={onChange}
                            integrationId={selectedIntegration.id}
                        />
                    )}
                </LemonField>
            )}
        </>
    )
}

function LinearConfigFields({
    linearIntegrations,
    selectedIntegration,
}: {
    linearIntegrations: IntegrationType[]
    selectedIntegration: IntegrationType | undefined
}): JSX.Element {
    if (linearIntegrations.length === 0) {
        return (
            <div className="rounded-lg border border-border p-4 text-secondary text-sm">
                No Linear integrations connected.{' '}
                <Link
                    to={api.integrations.authorizeUrl({
                        kind: 'linear',
                        next: window.location.pathname + window.location.search,
                    })}
                    disableClientSideRouting
                >
                    Connect Linear
                </Link>
            </div>
        )
    }

    return (
        <>
            <LemonField name="linearIntegrationId" label="Linear connection">
                <LemonSelect
                    options={linearIntegrations.map((integration) => ({
                        label: integration.display_name,
                        value: integration.id,
                    }))}
                />
            </LemonField>
            {selectedIntegration && (
                <LemonField name="linearTeamId" label="Team">
                    {({ value, onChange }) => (
                        <LinearTeamPicker
                            value={value}
                            onChange={(v) => onChange(v || '')}
                            integration={selectedIntegration}
                        />
                    )}
                </LemonField>
            )}
        </>
    )
}

export interface ErrorTrackingAlertWizardProps {
    onCancel: () => void
    onSwitchToTraditional: () => void
}

export function ErrorTrackingAlertWizard({
    onCancel,
    onSwitchToTraditional,
}: ErrorTrackingAlertWizardProps): JSX.Element {
    const { currentStep } = useValues(errorTrackingAlertWizardLogic)

    return (
        <div className="flex flex-col min-h-[400px]">
            <div className="max-w-lg mx-auto flex-1 w-full">
                {currentStep === 'destination' && <DestinationStep onBack={onCancel} />}
                {currentStep === 'trigger' && <TriggerStep />}
                {currentStep === 'configure' && <ConfigureStep />}
            </div>

            <p className="text-center text-xs text-muted mt-6">
                Need more control?{' '}
                <button type="button" onClick={onSwitchToTraditional} className="text-link hover:underline">
                    Go back to traditional editor
                </button>
            </p>
        </div>
    )
}

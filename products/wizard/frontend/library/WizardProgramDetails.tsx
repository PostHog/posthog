import { IconCloud, IconGithub, IconLaptop } from '@posthog/icons'
import {
    Badge,
    Button,
    Field,
    FieldDescription,
    FieldLabel,
    Item,
    ItemContent,
    ItemDescription,
    ItemTitle,
    Separator,
    Skeleton,
    Tabs,
    TabsList,
    TabsTrigger,
    Text,
} from '@posthog/quill-primitives'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { RunEnvironmentEnumApi, WizardProgramApi } from '../generated/api.schemas'
import { WIZARD_LOCAL_RUNS_VISIBLE } from '../wizardRunDisplay'
import { WizardCommand } from './WizardCommand'
import { WizardRepositoryPicker } from './WizardRepositoryPicker'

export function WizardProgramDetails({
    loading,
    program,
    command,
    environment,
    repository,
    githubIntegrationId,
    githubConnected,
    githubIntegrationLoading,
    connectGitHubUrl,
    creating,
    createError,
    commandCopied,
    selectionInvalidated,
    onEnvironmentChange,
    onRepositoryChange,
    onCreate,
    onCopyCommand,
}: {
    loading: boolean
    program: WizardProgramApi | null
    command: string
    environment: RunEnvironmentEnumApi
    repository: string
    githubIntegrationId: number | null
    githubConnected: boolean
    githubIntegrationLoading: boolean
    connectGitHubUrl: string
    creating: boolean
    createError: string | null
    commandCopied: boolean
    selectionInvalidated: boolean
    onEnvironmentChange: (environment: RunEnvironmentEnumApi) => void
    onRepositoryChange: (repository: string) => void
    onCreate: () => void
    onCopyCommand: () => void
}): JSX.Element {
    if (loading) {
        return (
            <div
                className="flex min-h-0 flex-1 flex-col gap-5 overflow-hidden p-5 @3xl:p-6"
                aria-label="Loading program details"
            >
                <div className="flex flex-col gap-2">
                    <Skeleton className="h-5 w-48" />
                    <Skeleton className="h-4 w-72 max-w-full" />
                </div>
                <div className="flex flex-col gap-2">
                    <Skeleton className="h-4 w-36" />
                    <Skeleton className="h-4 w-44" />
                </div>
                <Separator />
                <Skeleton className="h-8 w-44" />
                <div className="flex flex-col gap-2">
                    <Skeleton className="h-4 w-28" />
                    <Skeleton className="h-8 w-full" />
                    <Skeleton className="h-4 w-80 max-w-full" />
                </div>
                <Skeleton className="h-8 w-32" />
            </div>
        )
    }

    if (selectionInvalidated) {
        return (
            <Item tone="warning" variant="outline">
                <ItemContent>
                    <ItemTitle>This program is no longer available</ItemTitle>
                    <ItemDescription>Refresh the Library and choose another program.</ItemDescription>
                </ItemContent>
            </Item>
        )
    }

    if (!program) {
        return (
            <Text className="flex h-full items-center justify-center" size="sm" variant="muted">
                Select a program.
            </Text>
        )
    }

    const supportsCloud = program.supported_environments.includes('cloud')
    const supportsLocal = program.supported_environments.includes('local')

    return (
        <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-5 @3xl:p-6">
            <div className="flex flex-col gap-1">
                <Text render={<h3 />} size="lg" weight="semibold">
                    {program.name}
                </Text>
                <Text size="sm" variant="muted">
                    {program.description}
                </Text>
            </div>

            <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center gap-2">
                    <Text size="xs" weight="semibold" variant="muted">
                        Supported
                    </Text>
                    {supportsCloud && (
                        <Badge variant="info">
                            <IconCloud />
                            Cloud
                        </Badge>
                    )}
                    {WIZARD_LOCAL_RUNS_VISIBLE && supportsLocal && (
                        <Badge>
                            <IconLaptop />
                            Local
                        </Badge>
                    )}
                </div>
                <Text size="sm" variant="muted">
                    Runs with Wizard {program.wizard_version}
                </Text>
            </div>

            {WIZARD_LOCAL_RUNS_VISIBLE && supportsLocal && environment === 'cloud' && githubConnected && (
                <WizardCommand command={command} showCopyButton={false} copied={commandCopied} onCopy={onCopyCommand} />
            )}

            <Separator />

            <Tabs value={environment} onValueChange={(value) => onEnvironmentChange(value as RunEnvironmentEnumApi)}>
                <TabsList variant="line">
                    {supportsCloud && (
                        <TabsTrigger value="cloud">
                            Cloud{' '}
                            <Text size="xs" variant="muted">
                                Recommended
                            </Text>
                        </TabsTrigger>
                    )}
                    {WIZARD_LOCAL_RUNS_VISIBLE && supportsLocal && <TabsTrigger value="local">Local</TabsTrigger>}
                </TabsList>
            </Tabs>

            <div>
                {environment === 'cloud' ? (
                    githubIntegrationLoading ? (
                        <Text size="sm" variant="muted">
                            Checking the GitHub integration…
                        </Text>
                    ) : githubConnected ? (
                        <div className="flex flex-col gap-4">
                            <Field>
                                <FieldLabel>GitHub repository</FieldLabel>
                                {githubIntegrationId === null ? (
                                    <Text size="sm" variant="muted">
                                        Checking the GitHub integration…
                                    </Text>
                                ) : (
                                    <WizardRepositoryPicker
                                        integrationId={githubIntegrationId}
                                        value={repository}
                                        onChange={onRepositoryChange}
                                        disabledReason={creating ? 'A cloud run is starting.' : undefined}
                                    />
                                )}
                                <FieldDescription className="flex items-center gap-1">
                                    <IconGithub />
                                    Choose a repository available to the connected GitHub integration.
                                </FieldDescription>
                            </Field>

                            {createError && (
                                <Item tone="destructive" variant="outline">
                                    {createError}
                                </Item>
                            )}

                            <Button
                                variant="primary"
                                size="lg"
                                className="self-start"
                                onClick={() => onCreate()}
                                loading={creating}
                                disabled={!repository}
                            >
                                Start cloud run
                            </Button>
                        </div>
                    ) : (
                        <div className="flex flex-col gap-4">
                            <Item tone="warning" variant="outline">
                                <ItemContent>
                                    <ItemTitle>Connect GitHub to run this program in the cloud.</ItemTitle>
                                    <Button variant="outline" render={<LinkPrimitive to={connectGitHubUrl} />}>
                                        Connect GitHub
                                    </Button>
                                </ItemContent>
                            </Item>

                            {WIZARD_LOCAL_RUNS_VISIBLE && (
                                <div className="flex flex-col gap-2">
                                    <Text size="xs" weight="semibold" variant="muted">
                                        Local command
                                    </Text>
                                    <Text size="sm">You can still run this program from your project folder.</Text>
                                    <WizardCommand
                                        command={command}
                                        showCopyButton={false}
                                        copied={commandCopied}
                                        onCopy={onCopyCommand}
                                    />
                                </div>
                            )}
                        </div>
                    )
                ) : (
                    <div className="flex flex-col gap-2">
                        <Text render={<h4 />} size="lg" weight="semibold">
                            Run from your project folder
                        </Text>
                        <Text size="sm" variant="muted">
                            Open a terminal in the project root, then run:
                        </Text>
                        <WizardCommand command={command} showCopyButton copied={commandCopied} onCopy={onCopyCommand} />
                        <Text size="xs" variant="muted">
                            Requires Node.js 22.22 or later.
                        </Text>
                    </div>
                )}
            </div>
        </div>
    )
}

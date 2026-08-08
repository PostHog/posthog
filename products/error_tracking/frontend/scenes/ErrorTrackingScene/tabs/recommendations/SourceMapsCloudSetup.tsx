import { useActions, useValues } from 'kea'
import { TextMorph } from 'torph/react'

import { IconChevronDown, IconChevronLeft, IconChevronRight, IconExternal, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonSkeleton, Spinner } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { GitHubRepositoryPicker } from 'lib/integrations/GitHubIntegrationHelpers'
import { LoadingBar } from 'lib/lemon-ui/LoadingBar'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { DetectedProject, SCAN_STEPS, sourceMapsCloudSetupLogic } from './sourceMapsCloudSetupLogic'

/** The intro view's cloud setup row: account | repository | launch, as one control group. */
export function CloudSetupLauncher(): JSX.Element {
    const { integrations, githubIntegrations, selectedIntegration, selectedRepository, isStartingDetection } =
        useValues(sourceMapsCloudSetupLogic)
    const { setSelectedIntegrationId, setSelectedRepository, continueFromRepository } =
        useActions(sourceMapsCloudSetupLogic)

    if (integrations === null) {
        return <LemonSkeleton className="h-10" />
    }

    if (githubIntegrations.length === 0) {
        return (
            <div className="flex items-center justify-between gap-2">
                <span className="text-sm text-muted">Connect GitHub to scan a repository.</span>
                <LemonButton
                    type="secondary"
                    size="small"
                    to={api.integrations.authorizeUrl({ kind: 'github', next: urls.errorTracking() })}
                    disableClientSideRouting
                >
                    Connect GitHub
                </LemonButton>
            </div>
        )
    }

    const account = selectedIntegration ?? githubIntegrations[0]

    return (
        <div className="flex flex-col gap-1.5">
            <div className="flex items-center rounded border border-primary overflow-hidden">
                <LemonMenu
                    items={[
                        {
                            items: githubIntegrations.map((integration) => ({
                                label: integration.display_name,
                                icon: <img src={integration.icon_url} alt="" className="w-4 h-4 rounded" />,
                                active: integration.id === account.id,
                                onClick: () => setSelectedIntegrationId(integration.id),
                            })),
                        },
                        {
                            items: [
                                {
                                    label: 'Connect a different GitHub account',
                                    to: api.integrations.authorizeUrl({
                                        kind: 'github',
                                        next: urls.errorTracking(),
                                    }),
                                    disableClientSideRouting: true,
                                },
                                {
                                    label: 'Manage integrations',
                                    to: urls.settings('project-integrations'),
                                    sideIcon: <IconExternal />,
                                },
                            ],
                        },
                    ]}
                >
                    <LemonButton
                        type="tertiary"
                        icon={<img src={account.icon_url} alt="" className="w-4 h-4 rounded" />}
                        sideIcon={<IconChevronDown />}
                        className="rounded-none border-r border-primary self-stretch shrink-0 max-w-48"
                    >
                        <span className="truncate">{account.display_name}</span>
                    </LemonButton>
                </LemonMenu>
                <GitHubRepositoryPicker
                    integrationId={account.id}
                    value={selectedRepository ?? ''}
                    onChange={setSelectedRepository}
                    className="flex-1 min-w-0 overflow-hidden !border-none rounded-none !shadow-none"
                />
                <LemonButton
                    type="tertiary"
                    icon={<IconSparkles />}
                    className="rounded-none border-l border-primary self-stretch shrink-0"
                    onClick={continueFromRepository}
                    loading={isStartingDetection}
                    disabledReason={!selectedRepository ? 'Select a repository first' : undefined}
                    data-attr="error-tracking-cloud-setup-start"
                >
                    Set it up
                </LemonButton>
            </div>
            <span className="text-xs text-muted text-center">
                The agent sets up source maps and opens a pull request. Nothing to install.
            </span>
        </div>
    )
}

export function SourceMapsCloudSetup(): JSX.Element {
    return (
        <div className="flex flex-col gap-4 px-6 pt-2 pb-6 text-left">
            <ProjectStep />
        </div>
    )
}

function StepHeader({ title, description }: { title: string; description: string }): JSX.Element {
    return (
        <div>
            <h3 className="text-base font-semibold mb-0.5">{title}</h3>
            <p className="text-xs text-secondary mb-0">{description}</p>
        </div>
    )
}

function ProjectStep(): JSX.Element {
    const { isScanRunning, selectedDetection, detectionsLoading, isStartingDetection } =
        useValues(sourceMapsCloudSetupLogic)
    const { setStep, startDetection } = useActions(sourceMapsCloudSetupLogic)

    const report = !isScanRunning ? selectedDetection?.report : null
    const error = !isScanRunning ? selectedDetection?.error : null

    return (
        <>
            <StepHeader
                title="Select a project"
                description={
                    isScanRunning
                        ? 'Finding the projects in your repository. This usually takes about a minute.'
                        : 'Pick the project the agent should set up.'
                }
            />
            {isScanRunning ? (
                <ScanProgress />
            ) : error ? (
                <div className="flex flex-col gap-2">
                    <div className="text-sm text-danger break-words">
                        <span className="font-medium">Scan failed.</span> {error.message}
                    </div>
                    <div>
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={startDetection}
                            loading={isStartingDetection}
                        >
                            Try again
                        </LemonButton>
                    </div>
                </div>
            ) : selectedDetection && report ? (
                <div className="flex flex-col gap-2">
                    {report.projects.length > 0 ? (
                        <div className="rounded-lg border border-primary max-h-80 overflow-y-auto">
                            {report.projects.map((project) => (
                                <ProjectOption key={project.path} project={project} />
                            ))}
                        </div>
                    ) : (
                        <div className="rounded border border-dashed border-primary p-4 text-center text-sm text-muted">
                            The scan didn't find any projects that need source maps.
                        </div>
                    )}
                    <div className="flex items-center justify-between text-xs text-muted">
                        <span>Scanned {dayjs(selectedDetection.updated_at).fromNow()}</span>
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            onClick={startDetection}
                            loading={isStartingDetection}
                        >
                            Rescan
                        </LemonButton>
                    </div>
                </div>
            ) : (
                <div className="flex flex-col items-center gap-2 py-4">
                    {detectionsLoading ? (
                        <Spinner />
                    ) : (
                        <>
                            <span className="text-sm text-muted">No scan results for this repository yet.</span>
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={startDetection}
                                loading={isStartingDetection}
                            >
                                Start scan
                            </LemonButton>
                        </>
                    )}
                </div>
            )}
            <div className="pt-1">
                <LemonButton type="secondary" icon={<IconChevronLeft />} onClick={() => setStep('intro')}>
                    Back
                </LemonButton>
            </div>
        </>
    )
}

function ScanProgress(): JSX.Element {
    const { selectedDetection, scanStepIndex } = useValues(sourceMapsCloudSetupLogic)

    return (
        <div className="flex flex-col items-center gap-2 py-4">
            <TextMorph as="span" className="text-sm text-secondary">
                {SCAN_STEPS[scanStepIndex]}
            </TextMorph>
            <LoadingBar loadId={selectedDetection?.task_run_id} wrapperClassName="my-0 max-w-full" />
        </div>
    )
}

// The report carries wizard framework slugs; map the common ones to their display names.
const FRAMEWORK_LABELS: Record<string, string> = {
    nextjs: 'Next.js',
    react: 'React',
    sveltekit: 'SvelteKit',
    svelte: 'Svelte',
    astro: 'Astro',
    remix: 'Remix',
    vue: 'Vue',
    nuxt: 'Nuxt',
    angular: 'Angular',
    node: 'Node.js',
}

function frameworkLabel(project: DetectedProject): string {
    const label = FRAMEWORK_LABELS[project.framework] ?? project.framework
    return project.variant ? `${label} (${project.variant})` : label
}

function ProjectOption({ project }: { project: DetectedProject }): JSX.Element {
    const disabledReason = !project.instrumentable
        ? project.reason || "The agent can't set this project up automatically."
        : undefined

    const option = (
        // Intentionally inert: the cloud wizard run that a click will start ships separately.
        <button
            type="button"
            aria-disabled={!!disabledReason}
            className={cn(
                'group flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left transition-colors border-b border-primary last:border-b-0',
                disabledReason ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer hover:bg-fill-button-tertiary-hover'
            )}
            data-attr="error-tracking-cloud-setup-project"
        >
            <div className="flex flex-col min-w-0">
                <span className="text-sm font-medium truncate">
                    {project.path === '.' ? 'Repository root' : project.path}
                </span>
                <span className="text-xs text-secondary">{frameworkLabel(project)}</span>
            </div>
            {disabledReason ? (
                <span className="text-xs text-muted shrink-0">Needs manual setup</span>
            ) : (
                <IconChevronRight className="shrink-0 text-muted transition-colors group-hover:text-primary" />
            )}
        </button>
    )

    return disabledReason ? <Tooltip title={disabledReason}>{option}</Tooltip> : option
}

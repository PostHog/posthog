import { IconFolder, IconGithub } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { TZLabel } from 'lib/components/TZLabel'

import type { WizardRunApi } from '../generated/api.schemas'
import { wizardGithubRepositoryUrl, wizardWorkspaceLabel } from '../wizardRunDisplay'
import { WizardRunActionsMenu } from './WizardRunActionsMenu'
import { WizardRunEnvironmentTag } from './WizardRunEnvironmentTag'
import { WizardRunsEmptyState } from './WizardRunsEmptyState'
import { WizardRunStatusTag } from './WizardRunStatusTag'

export function WizardRunTable({
    runs,
    selectedRunId,
    loading,
    failed,
    hasActiveFilters,
    refreshing,
    cancelling,
    onOpenLibrary,
    onClearFilters,
    onRefreshRuns,
    onSelect,
    onRefreshRun,
    onCopyRunId,
    onCancel,
}: {
    runs: WizardRunApi[]
    selectedRunId: string | null
    loading: boolean
    failed: boolean
    hasActiveFilters: boolean
    refreshing: boolean
    cancelling: boolean
    onOpenLibrary: () => void
    onClearFilters: () => void
    onRefreshRuns: () => void
    onSelect: (run: WizardRunApi) => void
    onRefreshRun: (run: WizardRunApi) => void
    onCopyRunId: (runId: string) => void
    onCancel: (run: WizardRunApi) => void
}): JSX.Element {
    const columns: LemonTableColumns<WizardRunApi> = [
        {
            title: 'Program',
            key: 'program',
            render: (_, run) => (
                <div className="min-w-44">
                    <div className="font-semibold">{run.program.name}</div>
                    <div className="text-xs text-muted">Wizard {run.program.wizard_version}</div>
                </div>
            ),
        },
        {
            title: 'Workspace',
            key: 'workspace',
            render: (_, run) => {
                if (run.workspace.type === 'git_repository') {
                    return (
                        <LemonButton
                            size="small"
                            type="tertiary"
                            icon={<IconGithub />}
                            to={wizardGithubRepositoryUrl(run.workspace.repository)}
                            targetBlank
                            className="w-fit"
                            onClick={(e) => e.stopPropagation()}
                        >
                            {run.workspace.repository}
                        </LemonButton>
                    )
                }
                return (
                    <span className="inline-flex items-center gap-1 px-2 py-1 text-sm font-medium">
                        <IconFolder />
                        {wizardWorkspaceLabel(run)}
                    </span>
                )
            },
        },
        {
            title: 'Environment',
            key: 'environment',
            render: (_, run) => <WizardRunEnvironmentTag environment={run.environment} />,
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, run) => (
                <div className="flex min-w-36 flex-col items-start gap-1">
                    <WizardRunStatusTag status={run.status} />
                    {run.status === 'failed' && run.error_message && (
                        <span className="max-w-52 text-xs text-muted" title={run.error_message}>
                            {run.error_message}
                        </span>
                    )}
                </div>
            ),
        },
        {
            title: 'Started',
            key: 'started_at',
            render: (_, run) =>
                run.started_at ? (
                    <TZLabel time={run.started_at} className="whitespace-nowrap text-xs" />
                ) : (
                    <span className="whitespace-nowrap text-xs text-muted">Not started</span>
                ),
        },
    ]

    if (failed && runs.length === 0) {
        return (
            <LemonBanner type="error" action={{ children: 'Refresh', onClick: onRefreshRuns }}>
                <div className="font-semibold">Couldn’t load Wizard runs.</div>
                <div className="text-sm">Refresh the page and try again.</div>
            </LemonBanner>
        )
    }

    return (
        <LemonTable
            id="wizard-runs"
            dataSource={runs}
            columns={columns}
            rowKey="id"
            loading={loading}
            loadingSkeletonRows={7}
            nouns={['Wizard run', 'Wizard runs']}
            pagination={{ pageSize: 25, hideOnSinglePage: false, useUrl: false }}
            rowClassName="h-[68px]"
            rowStatus={(run) => (run.id === selectedRunId ? 'highlighted' : null)}
            onRow={(run) => ({ onClick: () => onSelect(run), className: 'cursor-pointer' })}
            emptyState={
                hasActiveFilters ? (
                    <EmptyMessage
                        title="No matching Wizard runs"
                        description="Try another search or clear the current filters."
                        buttonText="Clear filters"
                        buttonOnClick={onClearFilters}
                    />
                ) : (
                    <WizardRunsEmptyState onOpenLibrary={onOpenLibrary} />
                )
            }
            rowActions={(run) => (
                <WizardRunActionsMenu
                    run={run}
                    refreshing={refreshing}
                    cancelling={cancelling}
                    onView={onSelect}
                    onRefresh={onRefreshRun}
                    onCopyRunId={onCopyRunId}
                    onCancel={onCancel}
                />
            )}
        />
    )
}

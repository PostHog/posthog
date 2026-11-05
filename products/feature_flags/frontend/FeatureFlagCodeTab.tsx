import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSelect, LemonSkeleton, Link, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { FeatureFlagType } from '~/types'

import { featureFlagCodeAnalysisLogic } from './featureFlagCodeAnalysisLogic'
import { FeatureFlagCodeCleanupPanel } from './FeatureFlagCodeCleanupPanel'
import { FeatureFlagCodeReferenceCard } from './FeatureFlagCodeReferenceCard'
import { FeatureFlagImplementationPanel } from './FeatureFlagImplementationPanel'
import type { FeatureFlagCodeAnalysisApi } from './generated/api.schemas'

const RUNNING_STATUS_LABELS: Partial<Record<FeatureFlagCodeAnalysisApi['run_status'], string>> = {
    not_started: 'Starting the analysis',
    queued: 'Waiting to start',
    in_progress: 'Reading the repository',
}

export function FeatureFlagCodeTab({ id, featureFlag }: { id: number; featureFlag: FeatureFlagType }): JSX.Element {
    const logic = featureFlagCodeAnalysisLogic({ id })
    const {
        analysis,
        analysisLoaded,
        analysisLoadError,
        analysisLoading,
        pollingStopped,
        target,
        targetLoading,
        repository,
        isRunning,
        startingAnalysis,
        startError,
        cleanupOutcome,
        isCleanupRunning,
        openingCleanupPr,
        cleanupError,
        unavailable,
    } = useValues(logic)
    const {
        loadAnalysis,
        startAnalysis,
        selectRepository,
        reportGitHubLinkClicked,
        selectCleanupOutcome,
        openCleanupPr,
    } = useActions(logic)

    if (unavailable) {
        return (
            <LemonBanner type="info">
                Code analysis isn't available for this project right now. Reload the page to check again.
            </LemonBanner>
        )
    }

    if (!analysisLoaded && analysisLoadError) {
        return (
            <LemonBanner
                type="error"
                action={{
                    children: 'Try again',
                    onClick: () => loadAnalysis(),
                    'data-attr': 'feature-flag-code-analysis-reload',
                }}
            >
                Couldn't load the code analysis for this flag.
            </LemonBanner>
        )
    }

    if (!analysisLoaded || (!target && targetLoading)) {
        return (
            <div className="flex flex-col gap-2">
                <LemonSkeleton className="h-6 w-1/3" />
                <LemonSkeleton className="h-24" />
            </div>
        )
    }

    const noIntegration = target?.source === 'no_integration'

    if (!analysis && noIntegration) {
        return (
            <div className="flex flex-col items-start gap-2 max-w-160">
                <h3 className="m-0">Connect GitHub</h3>
                <p className="m-0 text-secondary">
                    Connect a GitHub repository to see every place your code checks this flag, and the code each outcome
                    runs.
                </p>
                <LemonButton
                    type="primary"
                    icon={<IconGithub />}
                    to={urls.settings('environment-integrations', 'integration-github')}
                    data-attr="feature-flag-code-analysis-connect-github"
                >
                    Connect GitHub
                </LemonButton>
            </div>
        )
    }

    const startDisabledReason = noIntegration
        ? 'Connect GitHub to analyze this flag again'
        : isRunning
          ? 'An analysis is already running'
          : isCleanupRunning
            ? 'Wait for the cleanup pull request to open'
            : !repository && target?.source === 'ambiguous'
              ? 'Choose a repository first'
              : undefined

    const startButton = (label: string): JSX.Element => (
        <LemonButton
            type={analysis ? 'secondary' : 'primary'}
            onClick={() => startAnalysis()}
            loading={startingAnalysis}
            disabledReason={startDisabledReason}
            data-attr="feature-flag-code-analysis-start"
        >
            {label}
        </LemonButton>
    )

    const repositoryPicker =
        target && target.candidates.length > 1 ? (
            <LemonSelect
                size="small"
                placeholder="Choose a repository"
                value={repository}
                onChange={(value) => value && selectRepository(value)}
                options={target.candidates.map((candidate) => ({ value: candidate, label: candidate }))}
                disabledReason={isRunning ? 'An analysis is already running' : undefined}
                data-attr="feature-flag-code-analysis-repository"
            />
        ) : repository ? (
            <span className="font-mono text-sm">{repository}</span>
        ) : null

    const result = analysis?.result

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-2">
                {repositoryPicker && <span className="text-secondary text-sm">Repository</span>}
                {repositoryPicker}
            </div>

            {startError && <LemonBanner type="error">{startError}</LemonBanner>}

            {!analysis ? (
                <div className="flex flex-col items-start gap-2 max-w-160">
                    <p className="m-0 text-secondary">
                        Find every place the repository checks this flag, and the code that runs when the flag is
                        enabled, disabled, or set to each variant. An agent reads the code and doesn't change it.
                    </p>
                    {startButton('Analyze code')}
                </div>
            ) : isRunning && pollingStopped ? (
                <LemonBanner
                    type="warning"
                    action={{
                        children: 'Check again',
                        onClick: () => loadAnalysis(),
                        loading: analysisLoading,
                        'data-attr': 'feature-flag-code-analysis-resume',
                    }}
                >
                    Couldn't get the latest status of this analysis. It may still be running.
                </LemonBanner>
            ) : isRunning ? (
                <div className="flex flex-wrap items-center gap-2">
                    <Spinner />
                    <span>{RUNNING_STATUS_LABELS[analysis.run_status] ?? 'Analyzing'}</span>
                    <span className="text-secondary">You can leave this page and come back.</span>
                    {analysis.can_view_task && (
                        <Link to={urls.taskDetail(analysis.task_id)} data-attr="feature-flag-code-analysis-task-link">
                            View task
                        </Link>
                    )}
                </div>
            ) : !result ? (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: () => startAnalysis(),
                        loading: startingAnalysis,
                        disabledReason: startDisabledReason,
                        'data-attr': 'feature-flag-code-analysis-retry',
                    }}
                >
                    {analysis.run_status === 'cancelled'
                        ? 'The analysis was canceled.'
                        : (analysis.error_message ?? "The analysis didn't finish.")}
                    {analysis.can_view_task && (
                        <>
                            {' '}
                            <Link to={urls.taskDetail(analysis.task_id)}>View task</Link>
                        </>
                    )}
                </LemonBanner>
            ) : (
                <>
                    {result.references.length === 0 ? (
                        <LemonBanner type="info">
                            <span className="font-mono">{result.repository}</span> has no checks of this flag.
                        </LemonBanner>
                    ) : (
                        <div className="flex flex-col gap-3">
                            {result.references.map((reference, index) => (
                                <FeatureFlagCodeReferenceCard
                                    key={`${reference.file}:${reference.check_line}:${index}`}
                                    reference={reference}
                                    repository={result.repository}
                                    commitSha={result.commit_sha}
                                    onGitHubLinkClick={reportGitHubLinkClicked}
                                />
                            ))}
                        </div>
                    )}
                    {result.notes && (
                        <div className="flex flex-col gap-1">
                            <h4 className="m-0">Notes</h4>
                            <p className="m-0 text-secondary whitespace-pre-wrap">{result.notes}</p>
                        </div>
                    )}
                    {result.references.length === 0 && (
                        <FeatureFlagImplementationPanel featureFlag={featureFlag} defaultOpen />
                    )}
                    <FeatureFlagCodeCleanupPanel
                        cleanup={analysis.cleanup}
                        repository={analysis.repository}
                        selectedOutcome={cleanupOutcome}
                        opening={openingCleanupPr}
                        error={cleanupError}
                        onSelectOutcome={selectCleanupOutcome}
                        onOpen={openCleanupPr}
                    />
                    <div className="flex flex-wrap items-center gap-2">
                        {startButton('Analyze again')}
                        <span className="text-secondary text-sm">
                            Analyzed <TZLabel time={analysis.created_at} /> at commit{' '}
                            <span className="font-mono">{result.commit_sha.slice(0, 7)}</span>
                        </span>
                    </div>
                </>
            )}
        </div>
    )
}

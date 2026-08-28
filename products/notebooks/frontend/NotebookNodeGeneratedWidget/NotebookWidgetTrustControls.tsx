import { LemonButton, LemonCheckbox } from '@posthog/lemon-ui'

export type NotebookWidgetTrustControlsProps = {
    buildHash: string | null
    canTrustScopes: boolean
    notebookTrusted: boolean
    projectTrusted: boolean
    variant: 'gate' | 'toolbar'
    onRun: () => void
    onViewSource: () => void
    onNotebookTrustedChange: (trusted: boolean) => void
    onProjectTrustedChange: (trusted: boolean) => void
}

export function NotebookWidgetTrustControls({
    buildHash,
    canTrustScopes,
    notebookTrusted,
    projectTrusted,
    variant,
    onRun,
    onViewSource,
    onNotebookTrustedChange,
    onProjectTrustedChange,
}: NotebookWidgetTrustControlsProps): JSX.Element {
    const scopeDisabledReason = canTrustScopes ? undefined : 'Sign in to save widget trust choices.'
    const shortBuildHash = buildHash ? buildHash.slice(0, 12) : null
    const scopeControls = (
        <div className={variant === 'gate' ? 'flex flex-col gap-2' : 'flex flex-wrap items-center gap-3'}>
            <LemonCheckbox
                checked={notebookTrusted}
                onChange={onNotebookTrustedChange}
                disabledReason={scopeDisabledReason}
                label="Trust all widgets in this notebook"
                size="small"
                data-attr="notebook-widget-trust-notebook"
            />
            <LemonCheckbox
                checked={projectTrusted}
                onChange={onProjectTrustedChange}
                disabledReason={scopeDisabledReason}
                label="Trust all widgets in this project"
                size="small"
                data-attr="notebook-widget-trust-project"
            />
        </div>
    )

    if (variant === 'toolbar') {
        return (
            <div className="flex flex-wrap items-center justify-between gap-2 border-b px-2 py-1.5">
                <div className="flex flex-wrap items-center gap-2">
                    <LemonButton size="xsmall" onClick={onViewSource} data-attr="notebook-widget-view-source">
                        View source
                    </LemonButton>
                    {shortBuildHash ? (
                        <span className="font-mono text-xs text-muted">Build {shortBuildHash}</span>
                    ) : null}
                </div>
                {scopeControls}
            </div>
        )
    }

    return (
        <div className="flex h-full min-h-48 items-center justify-center p-4 text-center">
            <div className="flex max-w-lg flex-col items-center gap-3">
                <div className="text-base font-semibold">Run this widget?</div>
                <div className="text-secondary">
                    This generated widget contains JavaScript and can request the notebook data declared by its source.
                    Review the source, then run this exact build.
                </div>
                {shortBuildHash ? (
                    <div className="font-mono text-xs text-muted">Build {shortBuildHash}</div>
                ) : (
                    <div className="text-warning">
                        This preview has no verifiable build hash. Regenerate it before running it.
                    </div>
                )}
                <div className="flex flex-wrap justify-center gap-2">
                    {buildHash ? (
                        <LemonButton type="primary" onClick={onRun} data-attr="notebook-widget-run">
                            Run widget
                        </LemonButton>
                    ) : null}
                    <LemonButton onClick={onViewSource} data-attr="notebook-widget-view-source">
                        View source
                    </LemonButton>
                </div>
                <div className="w-full rounded border bg-surface-primary p-3 text-left">{scopeControls}</div>
            </div>
        </div>
    )
}

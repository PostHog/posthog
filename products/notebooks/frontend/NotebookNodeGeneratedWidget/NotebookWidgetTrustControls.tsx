import { LemonButton, LemonTag, type LemonTagType } from '@posthog/lemon-ui'

import type { WidgetSecurityReviewApi } from 'products/notebooks/frontend/generated/api.schemas'

export type NotebookWidgetTrustControlsProps = {
    buildHash: string | null
    isEditable: boolean
    securityReview: WidgetSecurityReviewApi | null
    variant: 'gate' | 'toolbar'
    onRun: () => void
    onViewSource: () => void
}

const SEVERITY_LABELS: Record<WidgetSecurityReviewApi['severity'], string> = {
    none: 'No potential issues flagged',
    low: 'Low',
    medium: 'Medium',
    high: 'High',
    critical: 'Critical',
}

function severityTagType(severity: WidgetSecurityReviewApi['severity']): LemonTagType {
    if (severity === 'none') {
        return 'success'
    }
    if (severity === 'high' || severity === 'critical') {
        return 'danger'
    }
    return 'warning'
}

export function NotebookWidgetTrustControls({
    buildHash,
    isEditable,
    securityReview,
    variant,
    onRun,
    onViewSource,
}: NotebookWidgetTrustControlsProps): JSX.Element {
    const shortBuildHash = buildHash ? buildHash.slice(0, 12) : null
    const reviewTag = securityReview ? (
        <LemonTag type={severityTagType(securityReview.severity)}>
            Automated review: {SEVERITY_LABELS[securityReview.severity]}
        </LemonTag>
    ) : (
        <LemonTag type="muted">Automated review unavailable</LemonTag>
    )

    if (variant === 'toolbar') {
        return (
            <div className="flex flex-wrap items-center justify-between gap-2 border-b px-2 py-1.5">
                <div className="flex flex-wrap items-center gap-2">
                    <LemonButton size="xsmall" onClick={onViewSource} data-attr="notebook-widget-view-source">
                        View source
                    </LemonButton>
                    {reviewTag}
                    {shortBuildHash ? (
                        <span className="font-mono text-xs text-muted">Build {shortBuildHash}</span>
                    ) : null}
                </div>
            </div>
        )
    }

    const hasFindings = securityReview !== null && securityReview.severity !== 'none'
    const reviewPassed = securityReview?.severity === 'none'
    return (
        <div className="h-full min-h-48 overflow-auto p-4">
            <div className="mx-auto flex min-h-full max-w-2xl flex-col justify-center gap-3">
                <div className="flex flex-wrap items-center gap-2">
                    <div className="text-base font-semibold">
                        {hasFindings
                            ? 'Security review found potential issues'
                            : reviewPassed
                              ? 'Review this widget before running it'
                              : 'This widget has not been security reviewed'}
                    </div>
                    {reviewTag}
                </div>
                <div className="text-secondary">
                    {hasFindings
                        ? securityReview.summary
                        : reviewPassed
                          ? 'The automated review flagged no potential issues, but automated reviews can miss issues. View the source before running this generated widget.'
                          : 'This version was generated before automated reviews were available. View its source before deciding whether to run it.'}
                </div>
                {hasFindings ? (
                    <ul className="m-0 flex list-disc flex-col gap-2 pl-5 text-left">
                        {securityReview.findings.map((finding, index) => (
                            <li key={`${finding.severity}-${finding.title}-${index}`}>
                                <div className="flex flex-wrap items-center gap-2">
                                    <span className="font-semibold">{finding.title}</span>
                                    <LemonTag type={severityTagType(finding.severity)} size="small">
                                        {SEVERITY_LABELS[finding.severity]}
                                    </LemonTag>
                                </div>
                                <div className="text-secondary">{finding.details}</div>
                            </li>
                        ))}
                    </ul>
                ) : null}
                {shortBuildHash ? (
                    <div className="font-mono text-xs text-muted">Build {shortBuildHash}</div>
                ) : (
                    <div className="text-warning">
                        {isEditable
                            ? "This widget version can't be verified. Regenerate the widget before running it."
                            : "This widget version can't be verified. Ask an editor to regenerate it before running it."}
                    </div>
                )}
                <div className="flex flex-wrap gap-2">
                    {buildHash ? (
                        <LemonButton type="primary" onClick={onRun} data-attr="notebook-widget-run">
                            {hasFindings ? 'Run widget anyway' : 'Run widget'}
                        </LemonButton>
                    ) : null}
                    <LemonButton onClick={onViewSource} data-attr="notebook-widget-view-source">
                        View source
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}

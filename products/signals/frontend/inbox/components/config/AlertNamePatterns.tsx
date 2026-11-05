import { useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton, LemonTag, LemonTextArea, Spinner } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { AlertPatternPreviewAlertApi } from 'products/signals/frontend/generated/api.schemas'

import { alertNamePatternsLogic } from '../../logics/alertNamePatternsLogic'
import { SOURCE_ALERT_PATTERNS_MAX_COUNT, SOURCE_ALERT_PATTERN_MAX_LENGTH, SignalSourceConfig } from '../../types'

const DROP_REASON_LABELS: Record<string, string> = {
    blocked: 'Blocked',
    not_allowed: 'Not allowed',
}

function PreviewAlertRow({ alert }: { alert: AlertPatternPreviewAlertApi }): JSX.Element {
    const title = alert.name || alert.insight_name || 'Unnamed alert'
    const dropReason = DROP_REASON_LABELS[alert.outcome]
    return (
        <li className="flex min-w-0 items-center gap-2 px-2 py-1.5">
            <div className="flex min-w-0 flex-1 flex-col">
                <span className="truncate text-xs font-medium text-default">{title}</span>
                {alert.name && alert.insight_name ? (
                    <span className="truncate text-xs text-muted">{alert.insight_name}</span>
                ) : null}
            </div>
            {dropReason ? (
                <LemonTag className="shrink-0" size="small" type={alert.outcome === 'blocked' ? 'danger' : 'muted'}>
                    {dropReason}
                </LemonTag>
            ) : null}
        </li>
    )
}

function PreviewGroup({
    label,
    alerts,
    emptyText,
    dataAttr,
}: {
    label: string
    alerts: AlertPatternPreviewAlertApi[]
    emptyText: string
    dataAttr: string
}): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col gap-1" data-attr={dataAttr}>
            <span className="text-xs text-secondary">
                <span>{label} </span>
                <span translate="no">({alerts.length})</span>
            </span>
            {alerts.length === 0 ? (
                <span className="text-xs text-muted">{emptyText}</span>
            ) : (
                <ul className="m-0 max-h-48 list-none divide-y divide-primary overflow-y-auto rounded border border-primary bg-surface-primary p-0">
                    {alerts.map((alert) => (
                        <PreviewAlertRow key={alert.id} alert={alert} />
                    ))}
                </ul>
            )}
        </div>
    )
}

export function AlertNamePatterns({
    sourceConfig,
    disabledReason,
}: {
    sourceConfig: SignalSourceConfig
    disabledReason?: string
}): JSX.Element {
    const logic = alertNamePatternsLogic({ sourceConfig })
    const {
        allowText,
        blockText,
        patternErrors,
        preview,
        previewGroups,
        previewLoading,
        previewFailed,
        hasChanges,
        canSave,
        saving,
    } = useValues(logic)
    const { setAllowText, setBlockText, discard, save, loadPreview } = useActions(logic)
    const hasPatternError = !!patternErrors.allow || !!patternErrors.block

    return (
        <div className="flex flex-col gap-2 pt-1" data-attr="signal-source-alert-patterns">
            <div className="flex flex-col gap-0.5">
                <span className="text-xs font-semibold text-default">Filter alerts by name</span>
                <span className="text-xs text-secondary">
                    Each pattern is a regular expression that is checked against the alert name and the insight name.
                    Put one pattern per line, up to {SOURCE_ALERT_PATTERNS_MAX_COUNT} per list and{' '}
                    {SOURCE_ALERT_PATTERN_MAX_LENGTH} characters each. Matching is case sensitive. Start a pattern with
                    (?i) to ignore case.
                </span>
            </div>

            <LemonField.Pure
                label="Allow"
                labelClassName="text-xs"
                className="gap-1"
                htmlFor="signal-source-alert-allow-patterns"
                help="If you add any, only alerts that match one of them become signals."
                error={patternErrors.allow}
            >
                <LemonTextArea
                    id="signal-source-alert-allow-patterns"
                    value={allowText}
                    onChange={setAllowText}
                    placeholder="(?i)revenue"
                    minRows={2}
                    maxRows={6}
                    disabled={!!disabledReason || saving}
                    aria-invalid={!!patternErrors.allow}
                    data-attr="signal-source-alert-allow-patterns"
                />
            </LemonField.Pure>
            <LemonField.Pure
                label="Block"
                labelClassName="text-xs"
                className="gap-1"
                htmlFor="signal-source-alert-block-patterns"
                help="Alerts that match one of these never become signals, also when they match an allow pattern."
                error={patternErrors.block}
            >
                <LemonTextArea
                    id="signal-source-alert-block-patterns"
                    value={blockText}
                    onChange={setBlockText}
                    placeholder="(?i)test|draft"
                    minRows={2}
                    maxRows={6}
                    disabled={!!disabledReason || saving}
                    aria-invalid={!!patternErrors.block}
                    data-attr="signal-source-alert-block-patterns"
                />
            </LemonField.Pure>

            <div className="flex flex-col gap-1.5">
                <div className="flex items-center gap-1.5">
                    <span className="text-xs font-semibold text-default">Preview</span>
                    {previewLoading ? <Spinner className="text-xs" /> : null}
                </div>
                {hasPatternError ? (
                    <span className="text-xs text-secondary">
                        Fix the patterns above to see which alerts they let through.
                    </span>
                ) : previewFailed ? (
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="text-xs text-secondary">Couldn't load the preview.</span>
                        <LemonButton
                            type="secondary"
                            size="xsmall"
                            onClick={loadPreview}
                            data-attr="signal-source-alert-patterns-retry-preview"
                        >
                            Try again
                        </LemonButton>
                    </div>
                ) : !preview || !previewGroups ? (
                    <LemonSkeleton className="h-16 w-full" />
                ) : preview.alerts.length === 0 ? (
                    <span className="text-xs text-secondary">
                        This project has no enabled alerts yet, so there's nothing to preview.
                    </span>
                ) : (
                    <>
                        <PreviewGroup
                            label="Let through"
                            alerts={previewGroups.passed}
                            emptyText="These patterns drop every alert."
                            dataAttr="signal-source-alert-patterns-preview-passed"
                        />
                        <PreviewGroup
                            label="Dropped"
                            alerts={previewGroups.dropped}
                            emptyText="These patterns drop no alerts."
                            dataAttr="signal-source-alert-patterns-preview-dropped"
                        />
                        {preview.has_more ? (
                            <span className="text-xs text-muted">
                                Showing your {preview.alerts.length} newest enabled alerts.
                            </span>
                        ) : null}
                    </>
                )}
            </div>

            <div className="flex flex-wrap items-center justify-end gap-2">
                {hasChanges ? (
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        onClick={discard}
                        disabledReason={saving ? 'Saving' : undefined}
                        data-attr="signal-source-alert-patterns-discard"
                    >
                        Discard
                    </LemonButton>
                ) : null}
                <LemonButton
                    type="primary"
                    size="xsmall"
                    onClick={save}
                    loading={saving}
                    disabledReason={
                        disabledReason ??
                        (saving
                            ? undefined
                            : !hasChanges
                              ? 'No changes to save'
                              : hasPatternError
                                ? 'Fix the patterns first'
                                : !canSave
                                  ? 'Checking the patterns'
                                  : undefined)
                    }
                    data-attr="signal-source-alert-patterns-save"
                >
                    Save filters
                </LemonButton>
            </div>
        </div>
    )
}

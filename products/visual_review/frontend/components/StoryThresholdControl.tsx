import { useState } from 'react'

import { LemonButton, LemonInput, LemonTag } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import type { SnapshotApi } from '../generated/api.schemas'

// Colour bands relative to the effective threshold: comfortably under is green,
// approaching is yellow, at-or-over (the tier that would flag this as changed)
// is red. Purely a visual cue — the classifier still decides with the threshold.
function bandClass(value: number, threshold: number): string {
    if (threshold <= 0) {
        return 'bg-danger-highlight text-danger'
    }
    if (value >= threshold) {
        return 'bg-danger-highlight text-danger'
    }
    if (value >= threshold * 0.5) {
        return 'bg-warning-highlight text-warning-dark'
    }
    return 'bg-success-highlight text-success'
}

function formatPct(value: number): string {
    if (value > 0 && value < 0.1) {
        return '<0.1%'
    }
    return value < 1 ? `${value.toFixed(2)}%` : `${value.toFixed(1)}%`
}

// Structural difference the SSIM tier compares against, as a percentage.
function structuralDiffPercent(snapshot: SnapshotApi): number | null {
    if (snapshot.ssim_score == null) {
        return null
    }
    const clamped = Math.max(0, Math.min(1, snapshot.ssim_score))
    return (1 - clamped) * 100
}

function ThresholdRow({
    label,
    tooltip,
    measured,
    threshold,
    overridden,
}: {
    label: string
    tooltip: string
    measured: number | null
    threshold: number
    overridden: boolean
}): JSX.Element {
    return (
        <div className="flex items-center justify-between text-xs gap-2">
            <Tooltip title={tooltip}>
                <span className="text-muted cursor-help">{label}</span>
            </Tooltip>
            <div className="flex items-center gap-1">
                {measured != null ? (
                    <span
                        className={`font-mono tabular-nums rounded px-1 py-0 leading-none ${bandClass(
                            measured,
                            threshold
                        )}`}
                    >
                        {formatPct(measured)}
                    </span>
                ) : (
                    <span className="text-muted">—</span>
                )}
                <span className="text-muted">/ {formatPct(threshold)}</span>
                {overridden && (
                    <LemonTag type="highlight" size="small">
                        Edited
                    </LemonTag>
                )}
            </div>
        </div>
    )
}

interface StoryThresholdControlProps {
    snapshot: SnapshotApi
    isSaving?: boolean
    onSetThresholds: (pixelThresholdPercent: number | null, structuralThresholdPercent: number | null) => void
    onClearThresholds: () => void
}

/**
 * Sidebar control showing both diff tiers (pixel and structural) against their
 * effective thresholds, and letting a reviewer relax either threshold for the
 * whole story. Unlike tolerating a hash, an override holds across every future
 * run regardless of hash — the fix for stories with known rendering movement.
 */
export function StoryThresholdControl({
    snapshot,
    isSaving,
    onSetThresholds,
    onClearThresholds,
}: StoryThresholdControlProps): JSX.Element {
    const pixelThreshold = snapshot.pixel_threshold_percent ?? 0
    const structuralThreshold = snapshot.structural_threshold_percent ?? 0
    const pixelOverridden = !!snapshot.pixel_threshold_overridden
    const structuralOverridden = !!snapshot.structural_threshold_overridden
    const anyOverridden = pixelOverridden || structuralOverridden

    const [editing, setEditing] = useState(false)
    const [pixelInput, setPixelInput] = useState<number | undefined>(pixelThreshold)
    const [structuralInput, setStructuralInput] = useState<number | undefined>(structuralThreshold)

    const startEditing = (): void => {
        setPixelInput(pixelThreshold)
        setStructuralInput(structuralThreshold)
        setEditing(true)
    }

    return (
        <div>
            <h4 className="text-xs font-semibold text-muted mb-2">Thresholds</h4>
            <div className="space-y-2">
                <ThresholdRow
                    label="Pixel"
                    tooltip="Percentage of pixels that differ. The story is flagged as a pixel change when this reaches the threshold."
                    measured={snapshot.diff_percentage ?? null}
                    threshold={pixelThreshold}
                    overridden={pixelOverridden}
                />
                <ThresholdRow
                    label="Structural"
                    tooltip="Perceptual (SSIM) difference. Catches movement that shifts few pixels but changes structure; the story is flagged when this reaches the threshold."
                    measured={structuralDiffPercent(snapshot)}
                    threshold={structuralThreshold}
                    overridden={structuralOverridden}
                />

                {editing ? (
                    <div className="space-y-2 pt-1">
                        <div className="flex items-center justify-between gap-2">
                            <span className="text-xs text-muted">Pixel %</span>
                            <LemonInput
                                type="number"
                                size="small"
                                className="w-24"
                                value={pixelInput}
                                onChange={setPixelInput}
                                min={0}
                                max={100}
                                step={0.1}
                            />
                        </div>
                        <div className="flex items-center justify-between gap-2">
                            <span className="text-xs text-muted">Structural %</span>
                            <LemonInput
                                type="number"
                                size="small"
                                className="w-24"
                                value={structuralInput}
                                onChange={setStructuralInput}
                                min={0}
                                max={100}
                                step={0.1}
                            />
                        </div>
                        <div className="flex items-center gap-1">
                            <LemonButton
                                type="primary"
                                size="xsmall"
                                loading={isSaving}
                                data-attr="visual-review-story-thresholds-save"
                                onClick={() => {
                                    onSetThresholds(pixelInput ?? null, structuralInput ?? null)
                                    setEditing(false)
                                }}
                            >
                                Save
                            </LemonButton>
                            <LemonButton
                                type="secondary"
                                size="xsmall"
                                disabledReason={isSaving ? 'Saving…' : undefined}
                                onClick={() => setEditing(false)}
                            >
                                Cancel
                            </LemonButton>
                        </div>
                        <p className="text-xs text-muted">
                            Leave a field blank to use the global default for that tier.
                        </p>
                    </div>
                ) : (
                    <div className="flex items-center gap-1 pt-1">
                        <LemonButton
                            type="secondary"
                            size="xsmall"
                            data-attr="visual-review-story-thresholds-edit"
                            onClick={startEditing}
                        >
                            {anyOverridden ? 'Edit thresholds' : 'Set thresholds'}
                        </LemonButton>
                        {anyOverridden && (
                            <LemonButton
                                type="secondary"
                                size="xsmall"
                                loading={isSaving}
                                data-attr="visual-review-story-thresholds-reset"
                                onClick={onClearThresholds}
                            >
                                Reset
                            </LemonButton>
                        )}
                    </div>
                )}
            </div>
        </div>
    )
}

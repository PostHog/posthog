import { useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonModal, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { percentage } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { LabeledRow } from '../../components/LabeledRow'
import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { formatCreditCount } from '../../utils/credits'
import { replayScannerLogic } from '../replayScannerLogic'
import { SCANNER_TYPE_OPTIONS, modelName, modelNamingVariant, scannerTypeLabel } from '../types'
import { ClippedPreview } from './ClippedPreview'
import { ScannerRecordingFilters } from './ScannerRecordingFilters'

function EnabledText({ enabled }: { enabled: boolean }): JSX.Element {
    return <span>{enabled ? 'Enabled' : 'Disabled'}</span>
}

export function ScannerSetupCard({ scannerId }: { scannerId: string }): JSX.Element | null {
    const { scanner, experimentContext } = useValues(replayScannerLogic({ id: scannerId }))
    const { featureFlags } = useValues(featureFlagLogic)
    const [promptOpen, setPromptOpen] = useState(false)
    if (!scanner) {
        return null
    }
    const namingVariant = modelNamingVariant(featureFlags[FEATURE_FLAGS.REPLAY_VISION_MODEL_TIER_NAMING_EXPERIMENT])
    const config = scanner.scanner_config
    const targeting = scanner.experiment_targeting

    return (
        <div
            className="border rounded bg-surface-primary p-4 flex flex-col gap-3"
            data-attr="vision-scanner-setup-card"
        >
            <div className="flex items-center justify-between gap-2 border-b border-primary pb-2">
                <span className="text-sm font-medium">Configuration</span>
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    to={urls.replayVisionScannerConfigure(scannerId)}
                    disabledReason={getReplayVisionEditDisabledReason(scanner.user_access_level)}
                    data-attr="vision-setup-edit"
                >
                    Edit scanner
                </LemonButton>
            </div>

            <div className="flex flex-col gap-0.5">
                <span className="text-sm font-semibold">
                    <Tooltip
                        title={
                            SCANNER_TYPE_OPTIONS.find((option) => option.value === scanner.scanner_type)?.description
                        }
                    >
                        <span className="underline decoration-dotted underline-offset-2 cursor-help">
                            {scannerTypeLabel(scanner.scanner_type)}
                        </span>
                    </Tooltip>{' '}
                    · {modelName(scanner.model, namingVariant)}
                </span>
                {scanner.credits_per_observation != null && (
                    <span className="text-xs text-muted">
                        {formatCreditCount(scanner.credits_per_observation)} per scan
                    </span>
                )}
            </div>

            <LabeledRow label="Prompt">
                {config.prompt ? (
                    <div className="bg-surface-secondary border rounded p-2">
                        <ClippedPreview
                            clip="short"
                            buttonLabel="Show full prompt"
                            dataAttr="vision-setup-show-prompt"
                            onOpenFull={() => setPromptOpen(true)}
                        >
                            <div className="whitespace-pre-wrap text-sm">{config.prompt}</div>
                        </ClippedPreview>
                        <LemonModal isOpen={promptOpen} onClose={() => setPromptOpen(false)} title="Prompt" width={720}>
                            <div className="whitespace-pre-wrap font-mono text-sm bg-surface-tertiary border rounded p-3">
                                {config.prompt}
                            </div>
                        </LemonModal>
                    </div>
                ) : (
                    <span className="text-muted">—</span>
                )}
            </LabeledRow>

            {scanner.scanner_type === 'monitor' && (
                <LabeledRow
                    label="Inconclusive verdicts"
                    tooltip="When enabled, the model can answer 'inconclusive' instead of yes or no when a recording doesn't show enough to decide."
                >
                    <EnabledText enabled={!!scanner.scanner_config.allow_inconclusive} />
                </LabeledRow>
            )}
            {scanner.scanner_type === 'classifier' && (
                <>
                    <LabeledRow label="Categories">
                        {scanner.scanner_config.tags.length ? (
                            <div className="flex flex-wrap gap-1">
                                {scanner.scanner_config.tags.map((tag) => (
                                    <LemonTag key={tag} type="option">
                                        {tag}
                                    </LemonTag>
                                ))}
                            </div>
                        ) : (
                            <span className="text-muted">—</span>
                        )}
                    </LabeledRow>
                    <LabeledRow label="Multiple categories per recording">
                        <EnabledText enabled={!!scanner.scanner_config.multi_label} />
                    </LabeledRow>
                    <LabeledRow label="Freeform categories">
                        <EnabledText enabled={!!scanner.scanner_config.allow_freeform_tags} />
                    </LabeledRow>
                </>
            )}
            {scanner.scanner_type === 'scorer' && (
                <LabeledRow label="Scale">
                    {scanner.scanner_config.scale.min} to {scanner.scanner_config.scale.max}
                    {scanner.scanner_config.scale.label ? ` (${scanner.scanner_config.scale.label})` : ''}
                </LabeledRow>
            )}
            {scanner.scanner_type === 'summarizer' && scanner.scanner_config.length && (
                <LabeledRow label="Summary length">
                    <span className="capitalize">{scanner.scanner_config.length}</span>
                </LabeledRow>
            )}

            <LabeledRow label="Recordings">
                Scans {percentage(scanner.sampling_rate ?? 0, 1)} of matching recordings
            </LabeledRow>
            {targeting && (
                <LabeledRow label="Experiment">
                    {/* The name loads with the scanner; until then, or for an experiment the viewer can't open, the ID stands in. */}
                    <Link to={urls.experiment(targeting.experiment_id)}>
                        {experimentContext?.experiment.id === targeting.experiment_id
                            ? experimentContext.experiment.name
                            : `Experiment ${targeting.experiment_id}`}
                    </Link>
                    <span className="text-muted">
                        {' · '}
                        {targeting.variant ? `${targeting.variant} variant` : 'every variant'}
                    </span>
                </LabeledRow>
            )}
            <LabeledRow label="Filters">
                <div className="[&_.PropertyFilterButton]:h-6 [&_.PropertyFilterButton]:text-xs [&_.UniversalFilterButton]:h-6 [&_.UniversalFilterButton]:text-xs">
                    <ScannerRecordingFilters query={scanner.query} />
                </div>
            </LabeledRow>

            {(scanner.created_by || scanner.updated_at) && (
                <div className="border-t pt-2 flex flex-col gap-1 text-xs text-muted">
                    {scanner.created_by && (
                        <span className="flex items-center gap-1.5">
                            Created by <ProfilePicture user={scanner.created_by} size="xs" showName />
                        </span>
                    )}
                    {scanner.updated_at && (
                        <span>
                            Updated <TZLabel time={scanner.updated_at} />
                        </span>
                    )}
                </div>
            )}
        </div>
    )
}

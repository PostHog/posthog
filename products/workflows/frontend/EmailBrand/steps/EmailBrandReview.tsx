import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonFileInput, LemonInput, LemonLabel, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { emailBrandFlowLogic } from '../emailBrandFlowLogic'
import type { EmailBrandFlowProps } from '../emailBrandFlowLogic'
import { EmailBrandPreview } from '../EmailBrandPreview'
import { brandFields } from '../utils'

const labels = {
    name: 'Brand name',
    primary_color: 'Primary color',
    accent_color: 'Accent color',
    text_color: 'Text color',
    background_color: 'Background color',
    font_family: 'Font family',
}

export function EmailBrandReview(props: EmailBrandFlowProps): JSX.Element {
    const logic = emailBrandFlowLogic(props)
    const {
        draft,
        detection,
        editedFields,
        conflicts,
        logoConflict,
        logoEdited,
        busy,
        nothingFound,
        importedLogoLoading,
        logoUrl,
        preview,
        previewError,
        validationError,
        starterAttempted,
    } = useValues(logic)
    const {
        editField,
        pickLogo,
        uploadLogo,
        removeLogo,
        resolveConflict,
        resolveAllConflicts,
        resolveLogoConflict,
        detect,
        save,
        setStep,
        refreshPreview,
    } = useActions(logic)
    const hasConflicts = Object.keys(conflicts).length > 0 || !!logoConflict
    return (
        <div className="py-4 space-y-4">
            <div className="flex flex-wrap justify-between items-center gap-2">
                <h2 className="mb-0">Review your Email brand</h2>
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={() =>
                        draft.source_repository && logic.values.integrationId
                            ? detect(true)
                            : setStep(logic.values.integrationId ? 'repository' : 'connect')
                    }
                    loading={busy}
                    data-attr="email-brand-detect-again"
                >
                    Detect again
                </LemonButton>
            </div>
            {nothingFound && (
                <LemonBanner type="info">{`We read ${detection?.files_read.length ?? 0} files in ${detection?.repository} and found no brand signals. Fill it in, it takes a minute.`}</LemonBanner>
            )}
            {hasConflicts && (
                <LemonBanner type="warning">
                    <p>Detection found different values for fields you edited. Choose which values to keep.</p>
                    <div className="flex flex-wrap gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => resolveAllConflicts('mine')}
                            data-attr="email-brand-keep-all"
                        >
                            Keep all mine
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => resolveAllConflicts('detected')}
                            data-attr="email-brand-use-all"
                        >
                            Use all detected
                        </LemonButton>
                    </div>
                </LemonBanner>
            )}
            <div className="grid grid-cols-1 @min-[48rem]:grid-cols-2 gap-6">
                <div className="min-w-0 space-y-4">
                    {brandFields.map((field) => {
                        const source = draft.sources[field]
                        return (
                            <div key={field} className="space-y-1">
                                <LemonLabel htmlFor={`email-brand-${field}`}>{labels[field]}</LemonLabel>
                                <LemonInput
                                    id={`email-brand-${field}`}
                                    value={draft[field]}
                                    onChange={(value) => editField(field, value)}
                                    fullWidth
                                    maxLength={field === 'name' ? 255 : field === 'font_family' ? 100 : 7}
                                    disabledReason={busy ? 'Wait for the current request to finish' : undefined}
                                    data-attr={`email-brand-${field}`}
                                />
                                <div className="flex flex-wrap gap-1">
                                    {source ? (
                                        <Tooltip title={`${source.path}${source.line ? `, line ${source.line}` : ''}`}>
                                            <LemonTag wrap className="max-w-full">
                                                <span className="break-all">{`From ${source.path}`}</span>
                                            </LemonTag>
                                        </Tooltip>
                                    ) : (
                                        <LemonTag type="muted">Not found in repo</LemonTag>
                                    )}
                                    {editedFields.includes(field) && <LemonTag type="warning">Edited by you</LemonTag>}
                                    {detection?.proposal[field]?.default_theme && (
                                        <LemonTag type="warning">Default theme, pick a color</LemonTag>
                                    )}
                                </div>
                                {conflicts[field] && (
                                    <div className="border rounded p-2 space-y-2">
                                        <p className="mb-0 text-sm break-all">{`Detected: ${conflicts[field]?.value}`}</p>
                                        <div className="flex flex-wrap gap-2">
                                            <LemonButton
                                                size="small"
                                                type="secondary"
                                                onClick={() => resolveConflict(field, 'mine')}
                                                data-attr={`email-brand-keep-${field}`}
                                            >
                                                Keep mine
                                            </LemonButton>
                                            <LemonButton
                                                size="small"
                                                type="secondary"
                                                onClick={() => resolveConflict(field, 'detected')}
                                                data-attr={`email-brand-use-${field}`}
                                            >
                                                Use detected
                                            </LemonButton>
                                        </div>
                                    </div>
                                )}
                            </div>
                        )
                    })}
                    <div className="space-y-2">
                        <LemonLabel>Logo</LemonLabel>
                        {logoUrl && (
                            <img
                                src={logoUrl}
                                alt="Your Email brand logo"
                                className="max-w-40 max-h-20 object-contain"
                            />
                        )}
                        <div className="flex flex-wrap gap-2">
                            {detection?.logo_candidates.map((logo) => (
                                <LemonButton
                                    key={logo.path}
                                    type="secondary"
                                    size="small"
                                    onClick={() => pickLogo(logo.path)}
                                    loading={importedLogoLoading}
                                    disabledReason={
                                        busy && !importedLogoLoading
                                            ? 'Wait for the current request to finish'
                                            : undefined
                                    }
                                    data-attr="email-brand-pick-logo"
                                >
                                    <span className="break-all">{logo.path}</span>
                                </LemonButton>
                            ))}
                        </div>
                        <LemonFileInput
                            accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml"
                            multiple={false}
                            loading={importedLogoLoading}
                            disabledReason={busy ? 'Wait for the current request to finish' : undefined}
                            onChange={(files) => files[0] && uploadLogo(files[0])}
                            callToAction={
                                <LemonButton
                                    type="secondary"
                                    loading={importedLogoLoading}
                                    disabledReason={busy ? 'Wait for the current request to finish' : undefined}
                                >
                                    Upload a logo
                                </LemonButton>
                            }
                            showUploadedFiles={false}
                        />
                        <LemonButton
                            type="tertiary"
                            size="small"
                            onClick={removeLogo}
                            disabledReason={busy ? 'Wait for the current request to finish' : undefined}
                            data-attr="email-brand-no-logo"
                        >
                            Use the brand name instead
                        </LemonButton>
                        {logoEdited && <LemonTag type="warning">Edited by you</LemonTag>}
                        {logoConflict && (
                            <div className="border rounded p-2 space-y-2">
                                <p className="mb-0 text-sm break-all">
                                    {logoConflict.path
                                        ? `Detected: ${logoConflict.path}`
                                        : 'No logo found in this detection'}
                                </p>
                                <div className="flex flex-wrap gap-2">
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        onClick={() => resolveLogoConflict('mine')}
                                    >
                                        Keep mine
                                    </LemonButton>
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        onClick={() => resolveLogoConflict('detected')}
                                    >
                                        Use detected
                                    </LemonButton>
                                </div>
                            </div>
                        )}
                        {draft.sources.logo && (
                            <LemonTag wrap className="max-w-full">
                                <span className="break-all">{`From ${draft.sources.logo.path}`}</span>
                            </LemonTag>
                        )}
                    </div>
                </div>
                <div className="min-w-0 space-y-2">
                    {previewError && (
                        <LemonBanner type="warning">
                            {previewError}
                            <LemonButton size="small" onClick={refreshPreview}>
                                Try preview again
                            </LemonButton>
                        </LemonBanner>
                    )}
                    <EmailBrandPreview draft={draft} logoUrl={logoUrl} starter={preview} />
                </div>
            </div>
            <div className="flex flex-wrap justify-end gap-2 border-t pt-4">
                <LemonButton
                    type="primary"
                    onClick={() => save(props.entryPoint !== 'channels' && !starterAttempted)}
                    loading={busy}
                    disabledReason={hasConflicts ? 'Resolve the detected values first' : validationError}
                    data-attr="email-brand-save"
                >
                    {props.entryPoint === 'channels' || starterAttempted
                        ? 'Save Email brand'
                        : 'Save and create starter template'}
                </LemonButton>
            </div>
        </div>
    )
}

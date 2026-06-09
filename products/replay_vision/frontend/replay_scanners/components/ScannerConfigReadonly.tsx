import { LemonTag } from '@posthog/lemon-ui'

import { PropertyFilterButton } from 'lib/components/PropertyFilters/components/PropertyFilterButton'

import { AnyPropertyFilter } from '~/types'

import { ReplayScanner, modelLabel, scannerTypeLabel } from '../types'

function Row({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <div className="text-xs font-medium text-muted uppercase tracking-wide">{label}</div>
            <div className="text-sm">{children}</div>
        </div>
    )
}

function Multiline({ value }: { value: string | null | undefined }): JSX.Element {
    return <div className="whitespace-pre-wrap">{value || <span className="text-muted">—</span>}</div>
}

export function ScannerConfigReadonly({ scanner }: { scanner: ReplayScanner }): JSX.Element {
    const samplingPercent = Math.round((scanner.sampling_rate ?? 0) * 1000) / 10
    const filters = (scanner.query?.properties ?? []) as AnyPropertyFilter[]

    return (
        <div className="flex flex-col gap-5">
            <div className="grid grid-cols-2 gap-5">
                <Row label="Type">
                    <LemonTag type="option">{scannerTypeLabel(scanner.scanner_type)}</LemonTag>
                </Row>
                <Row label="Sampling">{samplingPercent}%</Row>
            </div>

            <Row label="Description">
                <Multiline value={scanner.description} />
            </Row>

            <Row label="Prompt">
                <Multiline value={scanner.scanner_config.prompt} />
            </Row>

            {scanner.scanner_type === 'summarizer' && <Row label="Summary length">{scanner.scanner_config.length}</Row>}

            {scanner.scanner_type === 'monitor' && (
                <Row label="Allow inconclusive verdicts">
                    {scanner.scanner_config.allow_inconclusive ? 'Yes' : 'No'}
                </Row>
            )}

            {scanner.scanner_type === 'classifier' && (
                <>
                    <Row label="Tag vocabulary">
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
                    </Row>
                    <div className="grid grid-cols-2 gap-5">
                        <Row label="Multiple tags per session">{scanner.scanner_config.multi_label ? 'Yes' : 'No'}</Row>
                        <Row label="Freeform tags">{scanner.scanner_config.allow_freeform_tags ? 'Yes' : 'No'}</Row>
                    </div>
                </>
            )}

            {scanner.scanner_type === 'scorer' && (
                <Row label="Scale">
                    {scanner.scanner_config.scale.min} – {scanner.scanner_config.scale.max}
                    {scanner.scanner_config.scale.label ? ` (${scanner.scanner_config.scale.label})` : ''}
                </Row>
            )}

            <Row label="Recording filters">
                {filters.length === 0 ? (
                    <span className="text-muted">All completed recordings</span>
                ) : (
                    <div className="flex flex-wrap gap-1">
                        {filters.map((filter, i) => (
                            <PropertyFilterButton key={i} item={filter} />
                        ))}
                    </div>
                )}
            </Row>

            <div className="grid grid-cols-2 gap-5">
                <Row label="Model">{modelLabel(scanner.model)}</Row>
                <Row label="Emit signals">{scanner.emits_signals ? 'Yes' : 'No'}</Row>
            </div>
        </div>
    )
}

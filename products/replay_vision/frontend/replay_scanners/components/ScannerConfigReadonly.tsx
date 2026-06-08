import { LemonTag } from '@posthog/lemon-ui'

import { PropertyFilterButton } from 'lib/components/PropertyFilters/components/PropertyFilterButton'

import { AnyPropertyFilter } from '~/types'

import { ReplayScanner } from '../types'
import { modelLabel, scannerTypeLabel } from '../types'

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
    const config = scanner.scanner_config
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
                <Multiline value={config?.prompt} />
            </Row>

            {scanner.scanner_type === 'summarizer' && config?.length && (
                <Row label="Summary length">{config.length}</Row>
            )}

            {scanner.scanner_type === 'monitor' && (
                <Row label="Allow inconclusive verdicts">{config?.allow_inconclusive ? 'Yes' : 'No'}</Row>
            )}

            {scanner.scanner_type === 'classifier' && (
                <>
                    <Row label="Tag vocabulary">
                        {config?.tags?.length ? (
                            <div className="flex flex-wrap gap-1">
                                {config.tags.map((tag) => (
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
                        <Row label="Multiple tags per session">{config?.multi_label ? 'Yes' : 'No'}</Row>
                        <Row label="Freeform tags">{config?.allow_freeform_tags ? 'Yes' : 'No'}</Row>
                    </div>
                </>
            )}

            {scanner.scanner_type === 'scorer' && config?.scale && (
                <Row label="Scale">
                    {config.scale.min} – {config.scale.max}
                    {config.scale.label ? ` (${config.scale.label})` : ''}
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

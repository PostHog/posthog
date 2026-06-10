import { LemonCard, LemonTag } from '@posthog/lemon-ui'

import { PropertyFilterButton } from 'lib/components/PropertyFilters/components/PropertyFilterButton'

import { AnyPropertyFilter } from '~/types'

import { ReplayScanner, modelLabel, scannerTypeLabel } from '../types'

function Row({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div>
            <div className="text-xs text-muted mb-0.5">{label}</div>
            <div className="text-sm">{children}</div>
        </div>
    )
}

function Multiline({ value }: { value: string | null | undefined }): JSX.Element {
    return <div className="whitespace-pre-wrap text-sm">{value || <span className="text-muted">—</span>}</div>
}

function YesNoTag({ value }: { value: boolean }): JSX.Element {
    return (
        <LemonTag size="medium" type={value ? 'success' : 'default'} className="self-start">
            {value ? 'Yes' : 'No'}
        </LemonTag>
    )
}

function BehaviorCardContent({ scanner }: { scanner: ReplayScanner }): JSX.Element {
    return (
        <>
            <Row label="Prompt">
                <Multiline value={scanner.scanner_config.prompt} />
            </Row>
            {scanner.scanner_type === 'summarizer' && <Row label="Summary length">{scanner.scanner_config.length}</Row>}
            {scanner.scanner_type === 'monitor' && (
                <Row label="Allow inconclusive verdicts">
                    <YesNoTag value={!!scanner.scanner_config.allow_inconclusive} />
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
                    <Row label="Multiple tags per session">
                        <YesNoTag value={!!scanner.scanner_config.multi_label} />
                    </Row>
                    <Row label="Freeform tags">
                        <YesNoTag value={!!scanner.scanner_config.allow_freeform_tags} />
                    </Row>
                </>
            )}
            {scanner.scanner_type === 'scorer' && (
                <Row label="Scale">
                    {scanner.scanner_config.scale.min} – {scanner.scanner_config.scale.max}
                    {scanner.scanner_config.scale.label ? ` (${scanner.scanner_config.scale.label})` : ''}
                </Row>
            )}
        </>
    )
}

export function ScannerConfigReadonly({ scanner }: { scanner: ReplayScanner }): JSX.Element {
    const samplingPercent = Math.round((scanner.sampling_rate ?? 0) * 1000) / 10
    const filters = (scanner.query?.properties ?? []) as AnyPropertyFilter[]

    return (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <LemonCard className="p-4" hoverEffect={false}>
                <div className="text-sm font-medium mb-3">Overview</div>
                <div className="flex flex-col gap-3">
                    <Row label="Type">
                        <LemonTag type="option" className="self-start">
                            {scannerTypeLabel(scanner.scanner_type)}
                        </LemonTag>
                    </Row>
                    <Row label="Description">
                        <Multiline value={scanner.description} />
                    </Row>
                </div>
            </LemonCard>

            <LemonCard className="p-4" hoverEffect={false}>
                <div className="text-sm font-medium mb-3">Behavior</div>
                <div className="flex flex-col gap-3">
                    <BehaviorCardContent scanner={scanner} />
                </div>
            </LemonCard>

            <LemonCard className="p-4" hoverEffect={false}>
                <div className="text-sm font-medium mb-3">Triggers &amp; runtime</div>
                <div className="flex flex-col gap-3">
                    <Row label="Sampling">{samplingPercent}%</Row>
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
                    <Row label="Model">{modelLabel(scanner.model)}</Row>
                    <Row label="Emit signals">
                        <YesNoTag value={scanner.emits_signals} />
                    </Row>
                </div>
            </LemonCard>
        </div>
    )
}

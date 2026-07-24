import { useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconCheckCircle, IconNotebook, IconPlus, IconTarget, IconThumbsDown, IconWarning } from '@posthog/icons'

import { LemonSnack } from 'lib/lemon-ui/LemonSnack/LemonSnack'
import { urls } from 'scenes/urls'

import { ScannerTypeBadge } from '../../components/ScannerTypeBadge'
import { replayScannerLogic } from '../replayScannerLogic'
import { ScannerTemplate, ScannerTemplateIcon, defaultScannerTemplates, newScanner } from '../scannerTemplates'
import { scannerTypeOutputHint } from '../types'

const TEMPLATE_ICONS: Record<ScannerTemplateIcon, JSX.Element> = {
    warning: <IconWarning />,
    notebook: <IconNotebook />,
    target: <IconTarget />,
    'thumbs-down': <IconThumbsDown />,
    check: <IconCheckCircle />,
}

function TemplateCard({ template }: { template: ScannerTemplate | 'blank' }): JSX.Element {
    const isBlank = template === 'blank'
    const { searchParams } = useValues(router)

    const handleClick = (): void => {
        const templateKey = isBlank ? null : template.key
        replayScannerLogic({ id: 'new' }).actions.resetScanner(newScanner(templateKey))
        const params = isBlank ? searchParams : { ...searchParams, template: template.key }
        router.actions.push(combineUrl(urls.replayVisionScannerConfigure('new'), params).url)
    }

    return (
        <button
            className="relative flex flex-col bg-bg-light border border-border rounded-lg hover:border-primary-3000-hover focus:border-primary-3000-hover focus:outline-none transition-colors text-left group p-6 cursor-pointer min-h-[180px]"
            data-attr={isBlank ? 'vision-template-blank' : `vision-template-${template.key}`}
            data-ph-capture-attribute-template={isBlank ? 'blank' : template.key}
            onClick={handleClick}
        >
            <div className="flex flex-col items-center text-center gap-4 h-full">
                <div className="bg-primary-3000/10 rounded-lg flex-shrink-0 size-12 flex items-center justify-center">
                    <span className="w-6 h-6 text-primary-3000 [&_svg]:w-6 [&_svg]:h-6">
                        {isBlank ? <IconPlus /> : TEMPLATE_ICONS[template.icon]}
                    </span>
                </div>
                <div className="flex-1 flex flex-col justify-start w-full">
                    <h3 className="text-base font-semibold text-default mb-2">
                        {isBlank ? 'Create from scratch' : template.name}
                    </h3>
                    <p className="text-sm text-secondary leading-relaxed mb-0">
                        {isBlank
                            ? 'Build a fully custom scanner with your own prompt and configuration.'
                            : template.description}
                    </p>
                    {/* Type chip + its output, stacked and pinned to the card's bottom edge (mt-auto) so this
                        footer lines up across the grid regardless of how many lines each description takes. */}
                    {!isBlank && (
                        <div className="mt-auto pt-4 flex flex-col items-center gap-1.5">
                            <ScannerTypeBadge scannerType={template.scanner_type} size="medium" />
                            <LemonSnack type="regular">
                                <span className="text-muted">Output:</span>{' '}
                                {scannerTypeOutputHint(template.scanner_type)}
                            </LemonSnack>
                        </div>
                    )}
                </div>
            </div>
        </button>
    )
}

export function ScannerTemplatePicker(): JSX.Element {
    return (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <TemplateCard template="blank" />
            {defaultScannerTemplates.map((template) => (
                <TemplateCard key={template.key} template={template} />
            ))}
        </div>
    )
}

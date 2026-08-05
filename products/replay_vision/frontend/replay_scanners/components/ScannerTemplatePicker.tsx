import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import {
    IconCheckCircle,
    IconNotebook,
    IconPencil,
    IconPlus,
    IconTarget,
    IconThumbsDown,
    IconTrash,
    IconWarning,
} from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { ScannerTypeBadge } from '../../components/ScannerTypeBadge'
import { replayScannerLogic } from '../replayScannerLogic'
import { ScannerTemplate, ScannerTemplateIcon, defaultScannerTemplates } from '../scannerTemplates'
import { scannerTypeOutputHint } from '../types'

const TEMPLATE_ICONS: Record<ScannerTemplateIcon, JSX.Element> = {
    warning: <IconWarning />,
    notebook: <IconNotebook />,
    target: <IconTarget />,
    'thumbs-down': <IconThumbsDown />,
    check: <IconCheckCircle />,
}

const CARD_CLASSES =
    'relative flex flex-col bg-bg-light border border-border rounded-lg hover:border-primary-3000-hover focus:border-primary-3000-hover focus:outline-none transition-colors text-left group p-6 cursor-pointer min-h-[180px]'

function TemplateCard({ template }: { template: ScannerTemplate | 'blank' }): JSX.Element {
    const isBlank = template === 'blank'
    const { searchParams } = useValues(router)

    const handleClick = (): void => {
        const templateKey = isBlank ? null : template.key
        replayScannerLogic({ id: 'new' }).actions.startFromTemplate(templateKey)
        const params = isBlank ? searchParams : { ...searchParams, template: template.key }
        router.actions.push(combineUrl(urls.replayVisionScannerConfigure('new'), params).url)
    }

    return (
        <button
            className={CARD_CLASSES}
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
                    {/* Type chip carries its output inline (e.g. "Monitor · yes or no"), pinned to the card's
                        bottom edge (mt-auto) so it lines up across the grid regardless of description length. */}
                    {!isBlank && (
                        <div className="mt-auto pt-4 flex justify-center">
                            <ScannerTypeBadge
                                scannerType={template.scanner_type}
                                size="medium"
                                suffix={
                                    <span className="opacity-75">· {scannerTypeOutputHint(template.scanner_type)}</span>
                                }
                            />
                        </div>
                    )}
                </div>
            </div>
        </button>
    )
}

function ResumeDraftCard(): JSX.Element | null {
    const logic = replayScannerLogic({ id: 'new' })
    const { scannerDraftSavedAt, scanner } = useValues(logic)
    const { startFromTemplate } = useActions(logic)
    const { searchParams } = useValues(router)

    if (scannerDraftSavedAt === null) {
        return null
    }

    const handleResume = (): void => {
        // The draft outranks any template param, so drop it.
        const { template: _template, ...params } = searchParams
        router.actions.push(combineUrl(urls.replayVisionScannerConfigure('new'), params).url)
    }

    return (
        <div
            role="button"
            tabIndex={0}
            className={CARD_CLASSES}
            data-attr="vision-template-resume-draft"
            onClick={handleResume}
            onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    handleResume()
                }
            }}
        >
            <div className="flex flex-col items-center text-center gap-4 h-full">
                <div className="bg-primary-3000/10 rounded-lg flex-shrink-0 size-12 flex items-center justify-center">
                    <span className="w-6 h-6 text-primary-3000 [&_svg]:w-6 [&_svg]:h-6">
                        <IconPencil />
                    </span>
                </div>
                <div className="flex-1 flex flex-col justify-start w-full">
                    <h3 className="text-base font-semibold text-default mb-2">Resume your draft</h3>
                    <p className="text-sm text-secondary leading-relaxed mb-0">
                        {scanner?.name ? `"${scanner.name}"` : 'Your unsaved scanner'}, saved{' '}
                        {dayjs(scannerDraftSavedAt).fromNow()}.
                    </p>
                    <div className="mt-auto pt-4 flex items-center justify-center gap-2">
                        {scanner?.scanner_type && <ScannerTypeBadge scannerType={scanner.scanner_type} size="medium" />}
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            icon={<IconTrash />}
                            tooltip="Discard this draft"
                            data-attr="vision-template-discard-draft"
                            onClick={(e) => {
                                e.stopPropagation()
                                startFromTemplate(null)
                            }}
                        />
                    </div>
                </div>
            </div>
        </div>
    )
}

export function ScannerTemplatePicker(): JSX.Element {
    return (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <ResumeDraftCard />
            <TemplateCard template="blank" />
            {defaultScannerTemplates.map((template) => (
                <TemplateCard key={template.key} template={template} />
            ))}
        </div>
    )
}

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
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
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

export function TemplateCard({ template }: { template: ScannerTemplate | 'blank' }): JSX.Element {
    const isBlank = template === 'blank'
    const { searchParams } = useValues(router)
    const { scannerDraftSavedAt } = useValues(replayScannerLogic({ id: 'new' }))

    const start = (): void => {
        const templateKey = isBlank ? null : template.key
        replayScannerLogic({ id: 'new' }).actions.startFromTemplate(templateKey)
        const params = isBlank ? searchParams : { ...searchParams, template: template.key }
        router.actions.push(combineUrl(urls.replayVisionScannerDetails('new'), params).url)
    }

    const handleClick = (): void => {
        if (scannerDraftSavedAt === null) {
            start()
            return
        }
        LemonDialog.open({
            title: 'Start over and lose your draft?',
            description: 'The scanner you have in progress will be replaced by this template.',
            primaryButton: { children: 'Start over', status: 'danger', onClick: start },
            secondaryButton: { children: 'Keep my draft' },
        })
    }

    return (
        <button
            className="flex flex-col bg-bg-light border border-border rounded-lg hover:border-primary-3000-hover focus:border-primary-3000-hover focus:outline-none transition-colors p-6 cursor-pointer min-h-[180px]"
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

function ResumeDraftBanner(): JSX.Element | null {
    const logic = replayScannerLogic({ id: 'new' })
    const { scannerDraftSavedAt, scanner } = useValues(logic)
    const { discardScannerDraft } = useActions(logic)
    const { searchParams } = useValues(router)

    if (scannerDraftSavedAt === null) {
        return null
    }

    const handleResume = (): void => {
        const { template: _template, ...params } = searchParams
        router.actions.push(combineUrl(urls.replayVisionScannerDetails('new'), params).url)
    }

    return (
        <LemonBanner
            type="info"
            icon={<IconPencil />}
            action={{
                children: 'Resume draft',
                onClick: handleResume,
                'data-attr': 'vision-template-resume-draft',
            }}
        >
            <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">Resume your draft</span>
                <span className="text-secondary font-normal">
                    {scanner?.name ? `"${scanner.name}"` : 'Untitled scanner'}
                </span>
                {scanner?.scanner_type && <ScannerTypeBadge scannerType={scanner.scanner_type} />}
                <span className="text-secondary font-normal">saved {dayjs(scannerDraftSavedAt).fromNow()}.</span>
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    status="danger"
                    icon={<IconTrash />}
                    tooltip="Discard this draft"
                    className="ml-auto"
                    data-attr="vision-template-discard-draft"
                    onClick={(): void =>
                        LemonDialog.open({
                            title: 'Discard this draft?',
                            description: 'This cannot be undone.',
                            primaryButton: {
                                children: 'Discard',
                                status: 'danger',
                                onClick: (): void => discardScannerDraft(),
                            },
                            secondaryButton: { children: 'Keep my draft' },
                        })
                    }
                />
            </div>
        </LemonBanner>
    )
}

export function ScannerTemplatePicker(): JSX.Element {
    return (
        <div className="flex flex-col gap-6">
            <ResumeDraftBanner />
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {defaultScannerTemplates.map((template) => (
                    <TemplateCard key={template.key} template={template} />
                ))}
                <TemplateCard template="blank" />
            </div>
        </div>
    )
}

import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import {
    IconCheckCircle,
    IconCopy,
    IconNotebook,
    IconPencil,
    IconPlus,
    IconTarget,
    IconThumbsDown,
    IconTrash,
    IconWarning,
} from '@posthog/icons'
import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { urls } from 'scenes/urls'

import { ScannerTypeBadge } from '../../components/ScannerTypeBadge'
import type { ReplayScannerTemplateApi } from '../../generated/api.schemas'
import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { replayScannerLogic } from '../replayScannerLogic'
import {
    ScannerTemplate,
    ScannerTemplateIcon,
    customScannerTemplateKey,
    defaultScannerTemplates,
    newScannerFromCustomTemplate,
} from '../scannerTemplates'
import { scannerTemplatesLogic } from '../scannerTemplatesLogic'
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
    const { scannerDraftSavedAt } = useValues(replayScannerLogic({ id: 'new' }))

    const start = (): void => {
        const templateKey = isBlank ? null : template.key
        replayScannerLogic({ id: 'new' }).actions.startFromTemplate(templateKey)
        const params = isBlank ? searchParams : { ...searchParams, template: template.key }
        router.actions.push(combineUrl(urls.replayVisionScannerConfigure('new'), params).url)
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

function CustomTemplateCard({
    template,
    deleting,
    onDelete,
}: {
    template: ReplayScannerTemplateApi
    deleting: boolean
    onDelete: () => void
}): JSX.Element {
    const { searchParams } = useValues(router)
    const logic = replayScannerLogic({ id: 'new' })
    const { scannerDraftSavedAt } = useValues(logic)
    // Templates have no per-object access level, so gate delete on the resource-level bar the backend enforces.
    const deleteDisabledReason = getReplayVisionEditDisabledReason()

    const start = (): void => {
        const templateKey = customScannerTemplateKey(template.id)
        // Same reset path as startFromTemplate: drop any saved draft so it can't outrank the template on reload.
        logic.actions.discardScannerDraft()
        logic.actions.resetScanner(newScannerFromCustomTemplate(template))
        router.actions.push(
            combineUrl(urls.replayVisionScannerConfigure('new'), { ...searchParams, template: templateKey }).url
        )
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
        <div className="relative bg-bg-light border border-border rounded-lg hover:border-primary-3000-hover focus-within:border-primary-3000-hover transition-colors min-h-[180px]">
            <button
                className="flex flex-col text-left p-6 cursor-pointer size-full focus:outline-none"
                data-attr={`vision-template-custom-${template.id}`}
                data-ph-capture-attribute-template="custom"
                onClick={handleClick}
            >
                <div className="flex flex-col items-center text-center gap-4 h-full">
                    <div className="bg-primary-3000/10 rounded-lg flex-shrink-0 size-12 flex items-center justify-center">
                        <IconCopy className="size-6 text-primary-3000" />
                    </div>
                    <div className="flex-1 flex flex-col justify-start w-full">
                        <h3 className="text-base font-semibold text-default mb-2">{template.name}</h3>
                        <p className="text-sm text-secondary leading-relaxed mb-0">
                            {template.description || 'A scanner template saved by your team.'}
                        </p>
                        <div className="mt-auto pt-4 flex justify-center">
                            <ScannerTypeBadge
                                scannerType={template.scanner_type}
                                size="medium"
                                suffix={
                                    <span className="opacity-75">· {scannerTypeOutputHint(template.scanner_type)}</span>
                                }
                            />
                        </div>
                    </div>
                </div>
            </button>
            <LemonButton
                className="absolute top-2 right-2"
                size="xsmall"
                type="tertiary"
                status="danger"
                icon={<IconTrash />}
                loading={deleting}
                disabledReason={deleting ? 'Deleting' : (deleteDisabledReason ?? undefined)}
                tooltip="Delete template"
                data-attr={`vision-template-custom-delete-${template.id}`}
                onClick={() =>
                    LemonDialog.open({
                        title: `Delete "${template.name}"?`,
                        description:
                            "Your team won't be able to use this template again. Scanners created from it won't change.",
                        primaryButton: {
                            children: 'Delete',
                            status: 'danger',
                            onClick: onDelete,
                        },
                        secondaryButton: { children: 'Cancel' },
                    })
                }
            />
        </div>
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
        router.actions.push(combineUrl(urls.replayVisionScannerConfigure('new'), params).url)
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
    const { customTemplates, customTemplatesLoading, deletingTemplateIds } = useValues(scannerTemplatesLogic)
    const { deleteTemplate } = useActions(scannerTemplatesLogic)

    return (
        <div className="flex flex-col gap-8">
            <ResumeDraftBanner />
            <section>
                <h2 className="text-lg font-semibold mb-4">Saved templates</h2>
                {customTemplatesLoading ? (
                    <div className="flex items-center gap-2 text-secondary">
                        <Spinner /> Loading saved templates
                    </div>
                ) : customTemplates.length === 0 ? (
                    <p className="text-secondary mb-0">
                        Open a scanner and select <strong>Save as template</strong> to add it here.
                    </p>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                        {customTemplates.map((template) => (
                            <CustomTemplateCard
                                key={template.id}
                                template={template}
                                deleting={deletingTemplateIds.includes(template.id)}
                                onDelete={() => deleteTemplate(template.id)}
                            />
                        ))}
                    </div>
                )}
            </section>
            <section>
                <h2 className="text-lg font-semibold mb-4">PostHog templates</h2>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    <TemplateCard template="blank" />
                    {defaultScannerTemplates.map((template) => (
                        <TemplateCard key={template.key} template={template} />
                    ))}
                </div>
            </section>
        </div>
    )
}

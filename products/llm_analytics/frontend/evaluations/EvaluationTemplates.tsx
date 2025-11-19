import { combineUrl, router } from 'kea-router'

import { IconArrowLeft, IconEye, IconPlus, IconShield, IconTarget, IconThumbsUp, IconWarning } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { EvaluationTemplate, defaultEvaluationTemplates } from './templates'

export const scene: SceneExport = {
    component: EvaluationTemplatesScene,
}

interface TemplateCardProps {
    template: EvaluationTemplate | 'blank'
}

function getTemplateIcon(icon: EvaluationTemplate['icon']): JSX.Element {
    const iconClass = 'w-6 h-6'
    switch (icon) {
        case 'target':
            return <IconTarget className={iconClass} />
        case 'thumbs-up':
            return <IconThumbsUp className={iconClass} />
        case 'shield':
            return <IconShield className={iconClass} />
        case 'eye':
            return <IconEye className={iconClass} />
        case 'alert-triangle':
            return <IconWarning className={iconClass} />
        default: {
            const exhaustiveCheck: never = icon
            return exhaustiveCheck
        }
    }
}

function TemplateCard({ template }: TemplateCardProps): JSX.Element {
    const isBlank = template === 'blank'

    const handleClick = (): void => {
        if (isBlank) {
            router.actions.push(urls.llmAnalyticsEvaluation('new'))
        } else {
            const url = combineUrl(urls.llmAnalyticsEvaluation('new'), { template: template.key }).url
            router.actions.push(url)
        }
    }

    return (
        <button
            className="relative flex flex-col bg-bg-light border border-border rounded-lg hover:border-primary-3000-hover focus:border-primary-3000-hover focus:outline-none transition-colors text-left group p-6 cursor-pointer min-h-[180px]"
            data-attr={isBlank ? 'blank-evaluation-template' : `evaluation-template-${template.key}`}
            onClick={handleClick}
        >
            <div className="flex flex-col items-center text-center gap-4 h-full">
                <div className="bg-primary-3000/10 rounded-lg p-3 flex-shrink-0">
                    {isBlank ? (
                        <IconPlus className="w-6 h-6 text-primary-3000" />
                    ) : (
                        <div className="text-primary-3000">{getTemplateIcon(template.icon)}</div>
                    )}
                </div>
                <div className="flex-1 flex flex-col justify-start">
                    <div className="flex items-center justify-center gap-2 mb-2">
                        <h3 className="text-base font-semibold text-default mb-0">
                            {isBlank ? 'Create from scratch' : template.name}
                        </h3>
                        {!isBlank && (
                            <LemonTag type="default" size="small">
                                Template
                            </LemonTag>
                        )}
                    </div>
                    <p className="text-sm text-secondary leading-relaxed">
                        {isBlank
                            ? 'Build a custom evaluation with your own prompt and configuration'
                            : template.description}
                    </p>
                </div>
            </div>
        </button>
    )
}

interface TemplateGridProps {
    title: string
    description: string
    showBackButton?: boolean
    minHeight?: '60vh' | '80vh'
}

function TemplateGrid({
    title,
    description,
    showBackButton = false,
    minHeight = '60vh',
}: TemplateGridProps): JSX.Element {
    return (
        <div className="flex flex-col items-center justify-center py-8" style={{ minHeight }}>
            <div className="w-full max-w-5xl px-4">
                {showBackButton && (
                    <div className="mb-6">
                        <LemonButton
                            type="secondary"
                            icon={<IconArrowLeft />}
                            onClick={() => router.actions.push(urls.llmAnalyticsEvaluations())}
                            size="small"
                        >
                            Back to Evaluations
                        </LemonButton>
                    </div>
                )}
                <div className="space-y-8">
                    <div className="text-center space-y-3">
                        <h1 className="text-3xl font-bold">{title}</h1>
                        <p className="text-base text-secondary max-w-2xl mx-auto">{description}</p>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                        <TemplateCard template="blank" />
                        {defaultEvaluationTemplates.map((template) => (
                            <TemplateCard key={template.key} template={template} />
                        ))}
                    </div>
                </div>
            </div>
        </div>
    )
}

export function EvaluationTemplatesScene(): JSX.Element {
    return (
        <TemplateGrid
            title="Choose an evaluation template"
            description="Select a pre-configured template to get started quickly, or create your own from scratch"
            showBackButton
            minHeight="80vh"
        />
    )
}

export function EvaluationTemplatesEmptyState(): JSX.Element {
    return (
        <TemplateGrid
            title="Create your first evaluation"
            description="Select a pre-configured template to get started quickly, or create your own from scratch"
            showBackButton={false}
            minHeight="60vh"
        />
    )
}

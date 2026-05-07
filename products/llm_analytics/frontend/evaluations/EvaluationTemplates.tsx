import { useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import posthog from 'posthog-js'

import { IconArrowLeft, IconCode, IconEye, IconPlus, IconTarget, IconThumbsUp, IconWarning } from '@posthog/icons'
import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { JudgeHog } from 'lib/components/hedgehogs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { EvaluationTemplate, defaultEvaluationTemplates } from './templates'

export const scene: SceneExport = {
    component: EvaluationTemplatesScene,
}

export type EvaluationTemplateChoice = EvaluationTemplate | 'blank'

interface TemplateCardProps {
    template: EvaluationTemplateChoice
    blankDescription?: string
    onSelectTemplate?: (template: EvaluationTemplateChoice) => void
}

function getTemplateIcon(icon: EvaluationTemplate['icon']): JSX.Element {
    const iconClass = 'w-6 h-6 text-primary-3000'
    switch (icon) {
        case 'target':
            return <IconTarget className={iconClass} />
        case 'thumbs-up':
            return <IconThumbsUp className={iconClass} />
        case 'eye':
            return <IconEye className={iconClass} />
        case 'alert-triangle':
            return <IconWarning className={iconClass} />
        case 'code':
            return <IconCode className={iconClass} />
        default: {
            const exhaustiveCheck: never = icon
            return exhaustiveCheck
        }
    }
}

function TemplateCard({ template, blankDescription, onSelectTemplate }: TemplateCardProps): JSX.Element {
    const isBlank = template === 'blank'
    const { searchParams } = useValues(router)

    const handleClick = (): void => {
        posthog.capture('llm evaluation template selected', {
            template_key: isBlank ? 'blank' : template.key,
        })

        if (onSelectTemplate) {
            onSelectTemplate(template)
            return
        }

        if (isBlank) {
            router.actions.push(combineUrl(urls.llmAnalyticsEvaluation('new'), searchParams).url)
        } else {
            const url = combineUrl(urls.llmAnalyticsEvaluation('new'), { ...searchParams, template: template.key }).url
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
                <div className="bg-primary-3000/10 rounded-lg flex-shrink-0 size-12 flex items-center justify-center">
                    {isBlank ? <IconPlus className="w-6 h-6 text-primary-3000" /> : getTemplateIcon(template.icon)}
                </div>
                <div className="flex-1 flex flex-col justify-start">
                    <div className="flex items-center justify-center gap-2 mb-2">
                        <h3 className="text-base font-semibold text-default mb-0">
                            {isBlank ? 'Create from scratch' : template.name}
                        </h3>
                        {!isBlank && (
                            <LemonTag type={template.evaluation_type === 'hog' ? 'option' : 'caution'} size="small">
                                {template.evaluation_type === 'hog' ? 'Hog' : 'LLM judge'}
                            </LemonTag>
                        )}
                    </div>
                    <p className="text-sm text-secondary leading-relaxed">
                        {isBlank
                            ? blankDescription || 'Build a custom evaluation with your own prompt and configuration'
                            : template.description}
                    </p>
                </div>
            </div>
        </button>
    )
}

interface EvaluationTemplatePickerProps {
    title: string
    description: string
    showBackButton?: boolean
    learnMoreUrl?: string
    minHeight?: '60vh' | '80vh' | 'auto'
    templates?: readonly EvaluationTemplate[]
    blankDescription?: string
    onSelectTemplate?: (template: EvaluationTemplateChoice) => void
}

export function EvaluationTemplatePicker({
    title,
    description,
    showBackButton = false,
    learnMoreUrl,
    minHeight = '60vh',
    templates = defaultEvaluationTemplates,
    blankDescription,
    onSelectTemplate,
}: EvaluationTemplatePickerProps): JSX.Element {
    const { searchParams } = useValues(router)
    const minHeightStyle = minHeight === 'auto' ? undefined : { minHeight }

    return (
        <div className="flex flex-col items-center justify-center py-8" style={minHeightStyle}>
            <div className="w-full max-w-5xl px-4">
                {showBackButton && (
                    <div className="mb-6">
                        <LemonButton
                            type="secondary"
                            icon={<IconArrowLeft />}
                            onClick={() =>
                                router.actions.push(combineUrl(urls.llmAnalyticsEvaluations(), searchParams).url)
                            }
                            size="small"
                        >
                            Back to Evaluations
                        </LemonButton>
                    </div>
                )}
                <div className="space-y-8">
                    <div className="text-center space-y-3">
                        <div className="flex justify-center mb-4">
                            <JudgeHog className="w-32 h-32" />
                        </div>
                        <h1 className="text-3xl font-bold">{title}</h1>
                        <p className="text-base text-secondary max-w-2xl mx-auto">
                            {description}
                            {learnMoreUrl && (
                                <>
                                    {' '}
                                    <Link to={learnMoreUrl} target="_blank">
                                        Learn more
                                    </Link>
                                </>
                            )}
                        </p>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                        <TemplateCard
                            template="blank"
                            blankDescription={blankDescription}
                            onSelectTemplate={onSelectTemplate}
                        />
                        {templates.map((template) => (
                            <TemplateCard key={template.key} template={template} onSelectTemplate={onSelectTemplate} />
                        ))}
                    </div>
                </div>
            </div>
        </div>
    )
}

export function EvaluationTemplatesScene(): JSX.Element {
    return (
        <EvaluationTemplatePicker
            title="Choose an evaluation template"
            description="Select a pre-configured template to get started quickly, or create your own from scratch"
            showBackButton
            minHeight="80vh"
        />
    )
}

export function EvaluationTemplatesEmptyState(): JSX.Element {
    return (
        <EvaluationTemplatePicker
            title="Create your first evaluation"
            description="Select a pre-configured template to get started quickly, or create your own from scratch."
            showBackButton={false}
            learnMoreUrl="https://posthog.com/docs/llm-analytics/evaluations"
            minHeight="60vh"
        />
    )
}

import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import posthog from 'posthog-js'

import { IconArrowLeft, IconFlask, IconPeople, IconPlus, IconTestTube, IconToggle } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { FlagIntent } from 'scenes/feature-flags/featureFlagIntentWarningLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { INTENT_KEYS, INTENT_METADATA, TEMPLATE_NAMES, TemplateKey } from './featureFlagTemplateConstants'
import { featureFlagTemplatesSceneLogic, navigateToNewFlag, SelectedTemplate } from './featureFlagTemplatesSceneLogic'

export const scene: SceneExport = {
    component: FeatureFlagTemplatesScene,
    logic: featureFlagTemplatesSceneLogic,
}

interface FeatureFlagTemplate {
    key: TemplateKey
    description: string
    icon: JSX.Element
}

const TEMPLATES: FeatureFlagTemplate[] = [
    {
        key: 'simple',
        description: 'Roll out to a percentage of all users',
        icon: <IconToggle className="w-6 h-6 text-primary-3000" />,
    },
    {
        key: 'targeted',
        description: 'Release to specific users or group segments',
        icon: <IconPeople className="w-6 h-6 text-primary-3000" />,
    },
    {
        key: 'multivariate',
        description: 'Test multiple variants with different payloads',
        icon: <IconTestTube className="w-6 h-6 text-primary-3000" />,
    },
    {
        key: 'targeted-multivariate',
        description: 'Test variants for specific user or group segments',
        icon: <IconFlask className="w-6 h-6 text-primary-3000" />,
    },
]

interface TemplateCardProps {
    template: FeatureFlagTemplate | 'blank'
    onClick: (key: SelectedTemplate) => void
}

function TemplateCard({ template, onClick }: TemplateCardProps): JSX.Element {
    const isBlank = template === 'blank'

    return (
        <button
            className="relative flex flex-col bg-bg-light border border-border rounded-lg hover:border-primary-3000-hover focus:border-primary-3000-hover focus:outline-none transition-colors text-left group p-6 cursor-pointer min-h-[180px]"
            data-attr={isBlank ? 'blank-feature-flag-template' : `feature-flag-template-${template.key}`}
            onClick={() => onClick(isBlank ? 'blank' : template.key)}
        >
            <div className="flex flex-col items-center text-center gap-4 h-full">
                <div className="bg-primary-3000/10 rounded-lg flex-shrink-0 size-12 flex items-center justify-center">
                    {isBlank ? <IconPlus className="w-6 h-6 text-primary-3000" /> : template.icon}
                </div>
                <div className="flex-1 flex flex-col justify-start">
                    <h3 className="text-base font-semibold text-default mb-2">
                        {isBlank ? 'Start from scratch' : TEMPLATE_NAMES[template.key]}
                    </h3>
                    <p className="text-sm text-secondary leading-relaxed">
                        {isBlank ? 'Default settings, customize everything yourself' : template.description}
                    </p>
                </div>
            </div>
        </button>
    )
}

function IntentCard({ intentKey, template }: { intentKey: FlagIntent; template: SelectedTemplate }): JSX.Element {
    const { searchParams } = useValues(router)
    const metadata = INTENT_METADATA[intentKey]
    const IntentIcon = metadata.icon

    const handleClick = (): void => {
        posthog.capture('feature flag intent selected', {
            intent: intentKey,
            template,
        })
        navigateToNewFlag(searchParams, template, intentKey)
    }

    return (
        <button
            className="relative flex flex-col bg-bg-light border border-border rounded-lg hover:border-primary-3000-hover focus:border-primary-3000-hover focus:outline-none transition-colors text-left group p-6 cursor-pointer min-h-[180px]"
            data-attr={`feature-flag-intent-${intentKey}`}
            onClick={handleClick}
        >
            <div className="flex flex-col items-center text-center gap-4 h-full">
                <div className="bg-primary-3000/10 rounded-lg flex-shrink-0 size-12 flex items-center justify-center">
                    <IntentIcon className="w-6 h-6 text-primary-3000" />
                </div>
                <div className="flex-1 flex flex-col justify-start">
                    <h3 className="text-base font-semibold text-default mb-2">{metadata.name}</h3>
                    <p className="text-sm text-secondary leading-relaxed">{metadata.description}</p>
                </div>
            </div>
        </button>
    )
}

function TemplateStep({ onSelect }: { onSelect: (key: SelectedTemplate) => void }): JSX.Element {
    const { searchParams } = useValues(router)

    return (
        <>
            <div className="mb-6">
                <LemonButton
                    type="secondary"
                    icon={<IconArrowLeft />}
                    onClick={() => router.actions.push(combineUrl(urls.featureFlags(), searchParams).url)}
                    size="small"
                >
                    Back to feature flags
                </LemonButton>
            </div>
            <div className="space-y-8">
                <div className="text-center space-y-3">
                    <h1 className="text-3xl font-bold">Create a feature flag</h1>
                    <p className="text-base text-secondary max-w-2xl mx-auto">
                        Choose a template or start from scratch
                    </p>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    <TemplateCard template="blank" onClick={onSelect} />
                    {TEMPLATES.map((template) => (
                        <TemplateCard key={template.key} template={template} onClick={onSelect} />
                    ))}
                </div>
            </div>
        </>
    )
}

function IntentStep({ template }: { template: SelectedTemplate }): JSX.Element {
    const { searchParams } = useValues(router)
    const { setSelectedTemplate } = useActions(featureFlagTemplatesSceneLogic)

    const templateName = template === 'blank' ? 'Start from scratch' : TEMPLATE_NAMES[template]

    const handleSkip = (): void => {
        posthog.capture('feature flag intent skipped', { template })
        navigateToNewFlag(searchParams, template)
    }

    return (
        <>
            <div className="mb-6">
                <LemonButton
                    type="secondary"
                    icon={<IconArrowLeft />}
                    onClick={() => setSelectedTemplate(null)}
                    size="small"
                >
                    Back to templates
                </LemonButton>
            </div>
            <div className="space-y-8">
                <div className="text-center space-y-3">
                    <p className="text-sm text-secondary">
                        Template: <span className="font-medium text-default">{templateName}</span>
                    </p>
                    <h1 className="text-3xl font-bold">Do you have specific requirements?</h1>
                    <p className="text-base text-secondary max-w-2xl mx-auto">
                        Tell us how you'll use this flag and we'll warn you about potential issues
                    </p>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-2xl mx-auto">
                    {INTENT_KEYS.map((key) => (
                        <IntentCard key={key} intentKey={key} template={template} />
                    ))}
                </div>
                <div className="text-center">
                    <LemonButton type="tertiary" onClick={handleSkip}>
                        Skip — I don't need evaluation warnings
                    </LemonButton>
                </div>
            </div>
        </>
    )
}

export function FeatureFlagTemplatesScene(): JSX.Element {
    const { featureFlagsV2Enabled, intentsEnabled, selectedTemplate } = useValues(featureFlagTemplatesSceneLogic)
    const { selectTemplate } = useActions(featureFlagTemplatesSceneLogic)

    if (!featureFlagsV2Enabled) {
        return <></>
    }

    return (
        <div className="flex flex-col items-center justify-center py-8 min-h-[80vh]">
            <div className="w-full max-w-5xl px-4">
                {selectedTemplate && intentsEnabled ? (
                    <IntentStep template={selectedTemplate} />
                ) : (
                    <TemplateStep onSelect={selectTemplate} />
                )}
            </div>
        </div>
    )
}

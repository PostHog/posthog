import { useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import posthog from 'posthog-js'

import { IconArrowLeft, IconFlask, IconPeople, IconPlus, IconTestTube, IconToggle } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

export const scene: SceneExport = {
    component: FeatureFlagTemplatesScene,
}

export type TemplateKey = 'simple' | 'targeted' | 'multivariate' | 'targeted-multivariate'

interface FeatureFlagTemplate {
    key: TemplateKey
    name: string
    description: string
    icon: JSX.Element
}

const TEMPLATES: FeatureFlagTemplate[] = [
    {
        key: 'simple',
        name: 'Percentage rollout',
        description: 'Roll out to a percentage of all users',
        icon: <IconToggle className="w-6 h-6 text-primary-3000" />,
    },
    {
        key: 'targeted',
        name: 'Targeted release',
        description: 'Release to specific users or group segments',
        icon: <IconPeople className="w-6 h-6 text-primary-3000" />,
    },
    {
        key: 'multivariate',
        name: 'A/B test variants',
        description: 'Test multiple variants with different payloads',
        icon: <IconTestTube className="w-6 h-6 text-primary-3000" />,
    },
    {
        key: 'targeted-multivariate',
        name: 'Targeted A/B test',
        description: 'Test variants for specific user or group segments',
        icon: <IconFlask className="w-6 h-6 text-primary-3000" />,
    },
]

interface TemplateCardProps {
    template: FeatureFlagTemplate | 'blank'
}

function TemplateCard({ template }: TemplateCardProps): JSX.Element {
    const isBlank = template === 'blank'
    const { searchParams } = useValues(router)

    const handleClick = (): void => {
        posthog.capture('feature flag template selected', {
            template_key: isBlank ? 'blank' : template.key,
        })

        if (isBlank) {
            router.actions.push(combineUrl(urls.featureFlag('new'), searchParams).url)
        } else {
            const url = combineUrl(urls.featureFlag('new'), { ...searchParams, template: template.key }).url
            router.actions.push(url)
        }
    }

    return (
        <button
            className="relative flex flex-col bg-bg-light border border-border rounded-lg hover:border-primary-3000-hover focus:border-primary-3000-hover focus:outline-none transition-colors text-left group p-6 cursor-pointer min-h-[180px]"
            data-attr={isBlank ? 'blank-feature-flag-template' : `feature-flag-template-${template.key}`}
            onClick={handleClick}
        >
            <div className="flex flex-col items-center text-center gap-4 h-full">
                <div className="bg-primary-3000/10 rounded-lg flex-shrink-0 size-12 flex items-center justify-center">
                    {isBlank ? <IconPlus className="w-6 h-6 text-primary-3000" /> : template.icon}
                </div>
                <div className="flex-1 flex flex-col justify-start">
                    <h3 className="text-base font-semibold text-default mb-2">
                        {isBlank ? 'Start from scratch' : template.name}
                    </h3>
                    <p className="text-sm text-secondary leading-relaxed">
                        {isBlank ? 'Default settings, customize everything yourself' : template.description}
                    </p>
                </div>
            </div>
        </button>
    )
}

export function FeatureFlagTemplatesScene(): JSX.Element {
    const { searchParams } = useValues(router)

    return (
        <div className="flex flex-col items-center justify-center py-8" style={{ minHeight: '80vh' }}>
            <div className="w-full max-w-5xl px-4">
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
                        <TemplateCard template="blank" />
                        {TEMPLATES.map((template) => (
                            <TemplateCard key={template.key} template={template} />
                        ))}
                    </div>
                </div>
            </div>
        </div>
    )
}

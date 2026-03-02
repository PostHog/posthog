import { useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import posthog from 'posthog-js'

import {
    IconArrowLeft,
    IconFlask,
    IconPeople,
    IconPlus,
    IconRocket,
    IconServer,
    IconTestTube,
    IconToggle,
} from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { FlagIntent } from 'scenes/feature-flags/featureFlagIntentWarningLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { INTENT_NAMES, TEMPLATE_NAMES, TemplateKey } from './featureFlagTemplateConstants'
import { featureFlagTemplatesSceneLogic } from './featureFlagTemplatesSceneLogic'

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

interface EvaluationIntent {
    key: FlagIntent
    description: string
    icon: JSX.Element
}

const INTENTS: EvaluationIntent[] = [
    {
        key: 'local-eval',
        description: 'Evaluate flags server-side without network requests for fastest performance',
        icon: <IconServer className="w-6 h-6 text-primary-3000" />,
    },
    {
        key: 'first-page-load',
        description: 'Ensure flags are available instantly on the very first page load',
        icon: <IconRocket className="w-6 h-6 text-primary-3000" />,
    },
]

function IntentCard({ intent }: { intent: EvaluationIntent }): JSX.Element {
    const { searchParams } = useValues(router)

    const handleClick = (): void => {
        posthog.capture('feature flag intent selected', { intent: intent.key })
        const url = combineUrl(urls.featureFlag('new'), { ...searchParams, intent: intent.key }).url
        router.actions.push(url)
    }

    return (
        <button
            className="relative flex flex-col bg-bg-light border border-border rounded-lg hover:border-primary-3000-hover focus:border-primary-3000-hover focus:outline-none transition-colors text-left group p-6 cursor-pointer min-h-[180px]"
            data-attr={`feature-flag-intent-${intent.key}`}
            onClick={handleClick}
        >
            <div className="flex flex-col items-center text-center gap-4 h-full">
                <div className="bg-primary-3000/10 rounded-lg flex-shrink-0 size-12 flex items-center justify-center">
                    {intent.icon}
                </div>
                <div className="flex-1 flex flex-col justify-start">
                    <h3 className="text-base font-semibold text-default mb-2">{INTENT_NAMES[intent.key]}</h3>
                    <p className="text-sm text-secondary leading-relaxed">{intent.description}</p>
                </div>
            </div>
        </button>
    )
}

export function FeatureFlagTemplatesScene(): JSX.Element {
    const { searchParams } = useValues(router)
    const { featureFlagsV2Enabled, intentsEnabled } = useValues(featureFlagTemplatesSceneLogic)

    // Show nothing while redirecting (redirect happens in logic afterMount)
    if (!featureFlagsV2Enabled) {
        return <></>
    }

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

                    {intentsEnabled && (
                        <>
                            <div className="text-center space-y-3">
                                <h2 className="text-xl font-semibold">Evaluation intents</h2>
                                <p className="text-sm text-secondary max-w-2xl mx-auto">
                                    Choose how you plan to evaluate this flag. We'll surface contextual warnings to help
                                    you avoid misconfiguration.
                                </p>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-2xl mx-auto">
                                {INTENTS.map((intent) => (
                                    <IntentCard key={intent.key} intent={intent} />
                                ))}
                            </div>
                        </>
                    )}
                </div>
            </div>
        </div>
    )
}

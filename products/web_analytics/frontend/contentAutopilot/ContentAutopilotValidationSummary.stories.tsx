import type { Meta, StoryFn } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { ContentAutopilotValidationSummary } from './ContentAutopilotValidationSummary'

const meta: Meta<typeof ContentAutopilotValidationSummary> = {
    title: 'Products/Web Analytics/Content autopilot/Validation summary',
    component: ContentAutopilotValidationSummary,
    parameters: {
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_PAGE_PERFORMANCE, FEATURE_FLAGS.WEB_ANALYTICS_CONTENT_AUTOPILOT],
    },
}

export default meta

const PASSED_CHECKS = [
    {
        check_key: 'structure',
        label: 'Page structure',
        passed: true,
        blocking: true,
        message: 'One H1, question-led sections, and enough depth.',
    },
    {
        check_key: 'internal_links',
        label: 'Internal links',
        passed: true,
        blocking: true,
        message: 'Every internal link points to a page in the sitemap.',
    },
    {
        check_key: 'sources',
        label: 'Sources',
        passed: true,
        blocking: true,
        message: 'Every sourced claim cites a page that was part of the research.',
    },
]

export const ReadyToDownload: StoryFn<typeof ContentAutopilotValidationSummary> = () => (
    <div className="w-[720px] p-4">
        <ContentAutopilotValidationSummary report={{ passed: true, checks: PASSED_CHECKS }} />
    </div>
)

export const NeedsFixes: StoryFn<typeof ContentAutopilotValidationSummary> = () => (
    <div className="w-[720px] p-4">
        <ContentAutopilotValidationSummary
            report={{
                passed: false,
                checks: [
                    ...PASSED_CHECKS,
                    {
                        check_key: 'grounding',
                        label: 'Sourced facts',
                        passed: false,
                        blocking: true,
                        message: "These claims aren't backed by a source: `Matomo is free to self-host`.",
                    },
                    {
                        check_key: 'length',
                        label: 'Length',
                        passed: false,
                        blocking: false,
                        message: '1,900 new words, well over the budget of about 1,200. Trim it before publishing.',
                    },
                ],
            }}
        />
    </div>
)

export const CouldNotDraft: StoryFn<typeof ContentAutopilotValidationSummary> = () => (
    <div className="w-[720px] p-4">
        <ContentAutopilotValidationSummary
            report={{
                passed: false,
                checks: [
                    {
                        check_key: 'generation',
                        label: 'Generation',
                        passed: false,
                        blocking: true,
                        message: "The AI model couldn't finish this draft. Regenerate to try again.",
                    },
                ],
            }}
        />
    </div>
)

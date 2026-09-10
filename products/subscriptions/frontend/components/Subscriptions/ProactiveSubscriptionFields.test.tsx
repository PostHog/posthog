import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'

import { ProactiveSubscriptionFields } from './ProactiveSubscriptionFields'

jest.mock('lib/hooks/useFeatureFlag', () => ({
    useFeatureFlag: () => true,
}))

jest.mock('lib/lemon-ui/LemonField', () => ({
    LemonField: ({
        children,
        name,
    }: {
        children?: ReactNode | ((field: { onChange: () => void; value: boolean }) => ReactNode)
        name?: string | string[]
    }) => {
        if (typeof children !== 'function') {
            return children
        }
        const field = Array.isArray(name) ? name.at(-1) : name
        return children({ onChange: jest.fn(), value: field === 'enabled' || field === 'allow_public_web_research' })
    },
}))

describe('ProactiveSubscriptionFields', () => {
    it('explains experiment drafts when proactive follow-up is enabled without a draft pull request', () => {
        render(
            <ProactiveSubscriptionFields
                proactiveConfig={{ enabled: true, create_draft_pr: false }}
                options={{
                    proactive_available: true,
                    public_web_research_available: true,
                    draft_pr_available: true,
                    repositories: [],
                }}
                optionsLoading={false}
                optionsLoadFailed={false}
                show
                onSelectRepository={jest.fn()}
                onRetry={jest.fn()}
            />
        )

        expect(
            screen.getByText(
                'When eligible, PostHog may also prepare an experiment draft. It stays inactive until someone starts it.'
            )
        ).toBeInTheDocument()
    })
})

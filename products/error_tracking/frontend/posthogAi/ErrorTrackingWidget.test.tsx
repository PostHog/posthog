import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import { Suspense } from 'react'

import { initKeaTests } from '~/test/init'

import { lookupToolRenderer } from 'products/posthog_ai/frontend/api/tools'

describe('ErrorTrackingWidget', () => {
    it('loads the declared renderer and displays returned issues', async () => {
        initKeaTests()
        const { Renderer } = lookupToolRenderer('search_error_tracking_issues', true)
        render(
            <Suspense fallback={<div>Loading widget</div>}>
                <Renderer
                    isLastInGroup
                    message={{
                        id: 'synthetic-error-search',
                        resolvedKey: 'search_error_tracking_issues',
                        innerToolName: 'search_error_tracking_issues',
                        rawServerName: 'posthog',
                        rawToolName: 'exec',
                        rawInput: { command: 'call search_error_tracking_issues {}' },
                        rawOutput: {
                            issues: [
                                {
                                    id: 'example-issue',
                                    name: 'Synthetic checkout error',
                                    status: 'active',
                                    library: 'web',
                                    occurrences: 12,
                                    users: 3,
                                },
                            ],
                        },
                        content: [],
                        status: 'completed',
                    }}
                />
            </Suspense>
        )
        expect(screen.getByText('Loading widget')).toBeInTheDocument()
        expect(await screen.findByText('Synthetic checkout error', {}, { timeout: 10000 })).toBeInTheDocument()
        expect(screen.queryByText('Loading widget')).not.toBeInTheDocument()
    })
})

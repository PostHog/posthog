import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import { Suspense } from 'react'

import { initKeaTests } from '~/test/init'

import { lookupToolRenderer } from 'products/posthog_ai/frontend/api/tools'

describe('ErrorTrackingWidget', () => {
    it('loads the declared renderer and falls back for the MCP issues-list response', async () => {
        initKeaTests()
        const { Renderer } = lookupToolRenderer('query-error-tracking-issues-list', true)
        render(
            <Suspense fallback={<div>Loading widget</div>}>
                <Renderer
                    isLastInGroup
                    message={{
                        id: 'synthetic-error-search',
                        resolvedKey: 'query-error-tracking-issues-list',
                        innerToolName: 'query-error-tracking-issues-list',
                        rawServerName: 'posthog',
                        rawToolName: 'exec',
                        rawInput: { command: 'call query-error-tracking-issues-list {}' },
                        rawOutput: {
                            results: [
                                {
                                    id: 'example-issue',
                                    name: 'Synthetic checkout error',
                                    status: 'active',
                                    library: 'web',
                                    aggregations: { occurrences: 12, users: 3 },
                                },
                            ],
                            hasMore: false,
                        },
                        content: [],
                        status: 'completed',
                    }}
                />
            </Suspense>
        )
        expect(screen.getByText('Loading widget')).toBeInTheDocument()
        expect(
            await screen.findByText('Call query-error-tracking-issues-list', {}, { timeout: 10000 })
        ).toBeInTheDocument()
        expect(screen.queryByText('Loading widget')).not.toBeInTheDocument()
        expect(screen.queryByText('No issues found')).not.toBeInTheDocument()
    })
})

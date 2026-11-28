import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { ExplanationContent } from './ExplanationContent'
import { LogExplanation } from './types'

// The shared react-markdown mock renders raw text, so parse just the image syntax here and
// hand it to the `img` component override the way react-markdown does.
jest.mock('react-markdown', () => {
    const React = jest.requireActual('react')
    const IMAGE = /!\[([^\]]*)\]\(([^)\s]+)\)/g
    const ReactMarkdown = ({ children, components }: { children: string; components?: Record<string, any> }): any => {
        const Img = components?.img ?? 'img'
        const parts: any[] = []
        let lastIndex = 0
        for (const match of children.matchAll(IMAGE)) {
            parts.push(children.slice(lastIndex, match.index))
            parts.push(React.createElement(Img, { key: match.index, src: match[2], alt: match[1] }))
            lastIndex = match.index! + match[0].length
        }
        parts.push(children.slice(lastIndex))
        return React.createElement('div', null, ...parts)
    }
    return { __esModule: true, default: ReactMarkdown, defaultUrlTransform: (url: string) => url }
})

describe('ExplanationContent', () => {
    afterEach(cleanup)

    const explanation: LogExplanation = {
        headline: 'Upstream request failed',
        severity_assessment: 'warning',
        impact_summary: 'Some requests returned errors.',
        probable_causes: [],
        immediate_actions: [],
        technical_explanation: 'See the chart: ![status chart](https://example.com/chart.png)',
        key_fields: [],
    }

    it.each([
        'https://example.com/chart.png',
        'https://us.i.posthog.com/chart.png',
        'https://eu.i.posthog.com/chart.png',
        '/chart.png',
    ])('renders the technical explanation image at %s as a link', (imageUrl) => {
        const { container } = render(
            <ExplanationContent
                explanation={{ ...explanation, technical_explanation: `See the chart: ![status chart](${imageUrl})` }}
            />
        )

        expect(container.querySelector('img')).toBeNull()
        expect(screen.getByText('status chart').closest('a')).toHaveAttribute('href', imageUrl)
    })
})

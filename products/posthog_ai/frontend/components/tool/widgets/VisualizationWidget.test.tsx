import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { LemonButton } from '@posthog/lemon-ui'

import { ArtifactContentType } from '~/queries/schema/schema-assistant-messages'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { VisualizationWidget } from './VisualizationWidget'

jest.mock('~/queries/Query/Query', () => ({
    Query: () => <div data-attr="visualization-query" />,
}))

describe('VisualizationWidget', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('wraps the real action row in a 520px container', () => {
        const { container } = render(
            <div data-attr="narrow-container" style={{ width: 520 }}>
                <VisualizationWidget
                    content={{
                        content_type: ArtifactContentType.Visualization,
                        query: { kind: NodeKind.HogQLQuery, query: 'SELECT 1' },
                    }}
                    extraActions={<LemonButton size="xsmall">Show on dashboard</LemonButton>}
                    openUrl="/insight/example"
                />
            </div>
        )

        expect(screen.getByTestId('narrow-container')).toHaveStyle({ width: '520px' })

        const actionRow = container.querySelector('[data-attr="visualization-widget-action-row"]')
        expect(actionRow).toHaveClass('min-w-0', 'flex-wrap')
        expect(container.querySelector('[data-attr="visualization-widget-heading"]')).toHaveClass('min-w-0', 'truncate')
        expect(container.querySelector('[data-attr="visualization-widget-actions"]')).toHaveClass(
            'shrink-0',
            'flex-wrap'
        )
        expect(screen.getByRole('button', { name: 'Show on dashboard' })).toBeInTheDocument()
    })
})

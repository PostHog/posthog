import { fireEvent, render, screen } from '@testing-library/react'

import { Sources } from './infrastructureTypes'
import { StageInspector } from './StageInspector'

describe('StageInspector', () => {
    it('shows an initial workflow read failure and lets the operator retry without displaying unrelated execution data', () => {
        const observed_at = new Date().toISOString()
        const sources: Sources = {
            dev_stack: {
                status: 'ok',
                observed_at,
                data: {
                    name: 'posthog-dev-stack',
                    base_image_reference: null,
                    workflow_url: 'https://example.com/current',
                    protected: true,
                    attempt_id: 'current',
                    workflow_run_id: 'current-run',
                },
            },
        }
        const props = { selected: 'dev_stack', sources, workflowLoading: false, onWorkflow: jest.fn() }
        const { rerender } = render(
            <StageInspector
                {...props}
                workflow={{ id: 'dev_stack', source: { status: 'error', data: null, observed_at: null } }}
            />
        )
        expect(screen.getByRole('alert').textContent).toContain('Could not read the build from Temporal')
        fireEvent.click(screen.getByText('Read latest build'))
        expect(props.onWorkflow).toHaveBeenCalledWith('dev_stack')
        rerender(
            <StageInspector
                {...props}
                workflow={{
                    id: 'dev_stack',
                    source: {
                        status: 'ok',
                        observed_at,
                        data: {
                            workflow_id: 'activate-dev-stack-image-previous',
                            run_id: 'previous-run',
                            status: 'completed',
                            url: 'https://example.com/previous',
                            activities: [],
                        },
                    },
                }}
            />
        )
        expect(screen.queryByRole('alert')).toBeNull()
        expect(screen.queryByText('completed')).toBeNull()
        expect(screen.getByText('Open Temporal history ↗').getAttribute('href')).toBe('https://example.com/current')
    })
})

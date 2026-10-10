import { render } from '@testing-library/react'

import { HogFlow } from '../hogflows/types'
import { renderWorkflowLogMessage } from './log-utils'

const workflow: HogFlow = {
    id: 'flow-1',
    team_id: 1,
    version: 1,
    name: 'Test workflow',
    status: 'draft',
    exit_condition: 'exit_only_at_end',
    actions: [],
    edges: [],
    created_at: '2026-08-24T00:00:00Z',
    updated_at: '2026-08-24T00:00:00Z',
}

describe('renderWorkflowLogMessage', () => {
    it('links a [Task:id|run_id] token to the created task', () => {
        const { container } = render(
            renderWorkflowLogMessage(
                workflow,
                'Stored action result in variable(s): task = [Task:8b70d61c-ca77-46fb-ba76-3330aaea3dad|80d1779f-6af1-4bfd-855b-556b3d7b2bc0]'
            )
        )

        const link = container.querySelector('a')
        expect(link?.getAttribute('href')).toContain('/desktop/task/8b70d61c-ca77-46fb-ba76-3330aaea3dad')
        expect(link?.getAttribute('target')).toBe('_blank')
        expect(link?.textContent).toContain('View task')
    })

    it.each([
        ['$feature_flag_called', '$feature_flag_called'],
        ['$pageview', null],
    ])(
        'names the event in the link of an [Event:...] token for %s only when it is a flag call',
        (eventName, linkedName) => {
            const { container } = render(
                renderWorkflowLogMessage(
                    workflow,
                    `Workflow woken by [Event:018f0000-0000-7000-8000-000000000002|${eventName}|2026-08-24T00:00:00.000Z]`
                )
            )

            const href = container.querySelector('a')?.getAttribute('href') ?? ''
            expect(href).toContain('/events/018f0000-0000-7000-8000-000000000002/')
            expect(new URL(href, 'http://localhost').searchParams.get('event')).toBe(linkedName)
        }
    )
})

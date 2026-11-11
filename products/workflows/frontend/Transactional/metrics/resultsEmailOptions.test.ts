import type { TransactionalEmailStatsRowApi } from 'products/messaging/frontend/generated/api.schemas'

import type { MessageTemplate } from '../../TemplateLibrary/types'
import { buildResultsEmailOptions } from './resultsEmailOptions'

function template(id: string, name: string, workflowId: string | null = `flow-${id}`): MessageTemplate {
    return { id, name, transactional_hog_flow_id: workflowId } as MessageTemplate
}

function row(key: string, sent: number): TransactionalEmailStatsRowApi {
    return { key, label: key, sent, delivered: sent, bounced: 0, complained: 0, opened: 0, clicked: 0, failed: 0 }
}

describe('buildResultsEmailOptions', () => {
    it('puts the busiest emails first and emails without sends last, by name', () => {
        const options = buildResultsEmailOptions(
            [
                template('a', 'Welcome'),
                template('b', 'Receipt'),
                template('c', 'Archive'),
                template('d', 'Sign-in code'),
                template('e', 'Not transactional', null),
            ],
            [row('d', 50), row('a', 9), row('gone', 400)]
        )
        expect(options).toEqual([
            { workflowId: 'flow-d', name: 'Sign-in code', sent: 50 },
            { workflowId: 'flow-a', name: 'Welcome', sent: 9 },
            { workflowId: 'flow-c', name: 'Archive', sent: 0 },
            { workflowId: 'flow-b', name: 'Receipt', sent: 0 },
        ])
    })
})

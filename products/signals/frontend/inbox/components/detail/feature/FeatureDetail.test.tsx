import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SignalReport, SignalReportArtefact } from '../../../types'
import { OpenQuestionItem } from './FeatureDetail'

const report = { id: 'feature-1', title: 'Widget', summary: 'A widget' } as SignalReport

describe('feature question drafts', () => {
    beforeEach(() => {
        useMocks({
            post: { '/api/environments/:team_id/file_system/log_view/': {} },
            get: {
                '/api/environments/:team_id/integrations/': { results: [] },
                '/api/users/@me/integrations/': { results: [] },
                '/api/users/@me/integrations/slack/linkable_workspaces/': { results: [] },
                '/api/projects/:team_id/signals/features/:id/planning_readiness/': {
                    ready: false,
                    missing: ['answers to open questions'],
                    planning_finished: false,
                },
                '/api/projects/:team_id/signals/reports/:id/artefacts': { results: [] },
                '/api/projects/:team_id/signals/reports/:id/signals/': [],
                '/api/projects/:team_id/signals/reports/available_reviewers/': [],
                '/api/projects/:team_id/signals/scout/configs/': [],
            },
        })
        initKeaTests()
    })
    afterEach(cleanup)

    it.each([{ options: ['Yes', 'No'] }, { options: [] }])(
        'preserves a custom answer with options $options after refocusing',
        ({ options }) => {
            const artefact = {
                id: 'question-1',
                type: 'question',
                created_at: new Date().toISOString(),
                content: { question: 'Enable this?', options, answered: false },
            } as SignalReportArtefact
            render(<OpenQuestionItem report={report} artefact={artefact} />)
            const input = options.length
                ? screen.getByRole('textbox', { name: 'Other answer' })
                : screen.getByPlaceholderText('Enter your answer')
            fireEvent.focus(input)
            fireEvent.change(input, { target: { value: 'Yes' } })
            expect(input).toHaveValue('Yes')
            fireEvent.change(input, { target: { value: 'Yes, for staff first' } })
            fireEvent.blur(input)
            fireEvent.focus(input)
            expect(input).toHaveValue('Yes, for staff first')
        }
    )
})

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Survey } from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { exampleRatingSurvey, exampleSurveyClient } from './apiSurvey.fixtures'
import { APISurveyFeedback } from './APISurveyFeedback'

describe('APISurveyFeedback', () => {
    beforeEach(initKeaTests)
    afterEach(cleanup)

    it.each([true, false])('loads, edits, and completes one response with partial responses: %s', async (partial) => {
        let respond!: (surveys: Survey[]) => void
        const client = {
            ...exampleSurveyClient(),
            getSurveys: (callback: (surveys: Survey[]) => void) => {
                respond = callback
            },
        }
        const capture = jest.spyOn(client, 'capture')
        render(
            <APISurveyFeedback
                surveyId={exampleRatingSurvey.id}
                instanceId="feedback"
                client={client}
                submissionId="shared-response"
            />
        )
        expect(screen.queryByRole('button', { name: 'Helpful' })).toBeNull()
        expect(capture).not.toHaveBeenCalled()
        await act(async () => respond([{ ...exampleRatingSurvey, enable_partial_responses: partial }]))
        fireEvent.click(await screen.findByRole('button', { name: 'Helpful' }))
        expect(screen.queryByText('Complete the survey to send your rating.') !== null).toBe(!partial)
        expect(screen.getByText('Selected: Helpful')).toBeTruthy()
        fireEvent.click(screen.getByRole('button', { name: 'Change' }))
        expect(screen.getByRole('button', { name: 'Helpful' })).toBe(document.activeElement)
        fireEvent.click(screen.getByRole('button', { name: 'Not helpful' }))
        expect(screen.getByText('Selected: Not helpful')).toBeTruthy()
        fireEvent.click(screen.getByRole('button', { name: 'Share more feedback' }))
        const input = await screen.findByRole('textbox')
        expect(screen.queryByRole('button', { name: 'Helpful' })).toBeNull()
        fireEvent.change(input, { target: { value: 'Find the settings' } })
        fireEvent.click(screen.getByLabelText('Yes'))
        fireEvent.click(screen.getByRole('button', { name: 'Send feedback' }))
        await waitFor(() => expect(screen.getByRole('status').textContent).toBe('Thanks for your feedback.'))
        expect(capture.mock.calls.filter(([event]) => event === 'survey shown')).toHaveLength(1)
        expect(
            capture.mock.calls
                .filter(([event]) => event === 'survey sent')
                .map(([, properties]) => ({
                    id: properties?.$survey_submission_id,
                    rating: properties?.$survey_response_helpfulness,
                    completed: properties?.$survey_completed,
                }))
        ).toEqual([
            ...(partial
                ? [
                      { id: 'shared-response', rating: '1', completed: false },
                      { id: 'shared-response', rating: '2', completed: false },
                  ]
                : []),
            { id: 'shared-response', rating: '2', completed: true },
        ])
        fireEvent.click(screen.getByRole('button', { name: 'close' }))
        await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
        expect(screen.queryByRole('button', { name: 'Share more feedback' })).toBeNull()
        expect(screen.queryByRole('button', { name: 'Change' })).toBeNull()
        expect(screen.getByRole('status')).toBe(document.activeElement)
    })
})

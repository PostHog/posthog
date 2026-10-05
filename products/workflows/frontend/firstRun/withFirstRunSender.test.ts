import welcomeSequence from '../../backend/templates/welcome_email_sequence_template.json'
import { HogFlowActionSchema } from '../Workflows/hogflows/steps/types'
import { withFirstRunSender } from './withFirstRunSender'

describe('withFirstRunSender', () => {
    it('assigns the sender to both welcome emails without changing content, other steps, or the source template', () => {
        const actions = HogFlowActionSchema.array().parse(welcomeSequence.actions)
        const original = structuredClone(actions)

        const transformed = withFirstRunSender(actions, { id: 42 })
        const emails = transformed.filter((action) => action.type === 'function_email')
        expect(emails).toHaveLength(2)
        expect(emails.map((action) => action.config.inputs.email.value.from)).toEqual([
            { integrationId: 42 },
            { integrationId: 42 },
        ])
        transformed.forEach((action, index) => {
            const originalAction = original[index]
            if (action.type === 'function_email' && originalAction.type === 'function_email') {
                const { from: originalFrom, ...originalEmail } = originalAction.config.inputs.email.value
                const { from: transformedFrom, ...transformedEmail } = action.config.inputs.email.value
                expect(transformedEmail).toEqual(originalEmail)
                expect(action.config.inputs.email.templating).toEqual(originalAction.config.inputs.email.templating)
            } else {
                expect(action).toBe(actions[index])
            }
        })
        expect(actions).toEqual(original)
    })
})

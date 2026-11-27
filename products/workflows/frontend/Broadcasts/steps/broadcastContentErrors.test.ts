import { missingContentReason } from './broadcastContentErrors'

describe('missingContentReason', () => {
    it.each([
        { errors: ['Add a subject line'], reason: 'Add a subject line' },
        {
            errors: ['Choose an email sender', 'Add a subject line', 'Add email content'],
            reason: 'Choose an email sender, add a subject line and add email content',
        },
        // A real problem has to be fixed where it shows, so Continue keeps its general message.
        { errors: ['Add a subject line', 'Liquid template error: tag "endif" not found'], reason: undefined },
        { errors: [], reason: undefined },
    ])('says what is still missing: $errors', ({ errors, reason }) => {
        expect(missingContentReason(errors)).toBe(reason)
    })
})

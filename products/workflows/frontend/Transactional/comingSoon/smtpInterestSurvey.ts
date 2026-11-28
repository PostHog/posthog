import { ComingSoonInterestSurvey } from './useComingSoonInterestSurvey'

// The api-type survey "Workflows: SMTP sending interest" in PostHog's own project.
export const SMTP_INTEREST_SURVEY: ComingSoonInterestSurvey = {
    surveyId: '01a1b1bc-e8e4-0000-653f-c9f58eae9f80',
    interestQuestionId: 'bdfa9649-3cbc-4f4f-b10e-8c4b93a085c8',
    noteQuestionId: '9fb44d9c-a600-49ba-8650-357a531ebbde',
    // pinned: the survey's third question, so this text, the choice values and the id must match the survey
    choiceQuestion: {
        id: 'd9981be7-4d09-449a-a061-7a34b57e9678',
        question: 'Which of these do you want to do?',
        choices: [
            {
                value: 'Send email from my app or tool through PostHog',
                description: 'For example, a billing system, a CRM, or your own backend',
            },
            {
                value: 'Send the emails I create in PostHog through my own provider',
                description: 'For example, Postmark, Resend, or Mailgun',
            },
            { value: 'Not sure yet' },
        ],
    },
    surface: 'transactional-smtp',
}

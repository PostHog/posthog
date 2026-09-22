/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Ask the decision model typed questions about one piece of text and get a calibrated probability per question.
 * @summary Ask the decision model
 */
export const mlInferenceDecisionsDecideCreateBodyModelDefault = `posthog/posthog/decision-4b`

export const MlInferenceDecisionsDecideCreateBody = /* @__PURE__ */ zod.object({
    state: zod
        .string()
        .describe('The text the questions are about, for example a support ticket or a session summary.'),
    questions: zod
        .record(
            zod.string(),
            zod.object({
                type: zod
                    .enum(['noul', 'choice', 'score'])
                    .describe('\* `noul` - Yes or no\n\* `choice` - Multiple choice\n\* `score` - Rating scale')
                    .describe(
                        'What kind of answer to produce: a yes\/no probability, one of the given options, or a rating.\n\n\* `noul` - Yes or no\n\* `choice` - Multiple choice\n\* `score` - Rating scale'
                    ),
                instructions: zod.string().describe('The question to ask about the state, phrased for the model.'),
                criteria: zod
                    .record(zod.string(), zod.string().describe('What this option means.'))
                    .optional()
                    .describe(
                        'For a multiple choice question, the options keyed by name. Omitted for other question types.'
                    ),
            })
        )
        .describe('The questions to ask, keyed by an id of your choice. Answers come back under the same ids.'),
    model: zod
        .string()
        .default(mlInferenceDecisionsDecideCreateBodyModelDefault)
        .describe('The decision model to ask, as a gateway model id.'),
})

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
export const mlInferenceDecisionsDecideCreateBodyStateMax = 65536

export const mlInferenceDecisionsDecideCreateBodyQuestionsInstructionsMax = 2000

export const mlInferenceDecisionsDecideCreateBodyModelDefault = `posthog/posthog/decision-4b`
export const mlInferenceDecisionsDecideCreateBodyModelMax = 200

export const MlInferenceDecisionsDecideCreateBody = /* @__PURE__ */ zod.object({
    state: zod
        .string()
        .max(mlInferenceDecisionsDecideCreateBodyStateMax)
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
                instructions: zod
                    .string()
                    .max(mlInferenceDecisionsDecideCreateBodyQuestionsInstructionsMax)
                    .describe('The question to ask about the state, phrased for the model.'),
                criteria: zod
                    .union([zod.record(zod.string(), zod.string()), zod.array(zod.string())])
                    .optional()
                    .describe(
                        'For a multiple choice question, the options keyed by name. For a rating question, the scale labels in order from lowest to highest, at least two. Omitted for a yes\/no question.'
                    ),
            })
        )
        .describe(
            'The questions to ask, keyed by an id of your choice, at most 32 per request. Answers come back under the same ids.'
        ),
    model: zod
        .string()
        .max(mlInferenceDecisionsDecideCreateBodyModelMax)
        .default(mlInferenceDecisionsDecideCreateBodyModelDefault)
        .describe('The decision model to ask, as a gateway model id.'),
})

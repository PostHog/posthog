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

export const mlInferenceDecisionsDecideCreateBodyModelDefault = `posthog/hogference/jevk5-fp8-0.2`
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

/**
 * Guess which filter picker tab a search belongs to, so the picker can suggest or promote it.
 * @summary Classify a filter picker search
 */
export const mlInferenceSearchIntentClassifyCreateBodyQueryMax = 200

export const mlInferenceSearchIntentClassifyCreateBodyActiveGroupTypeMax = 100

export const mlInferenceSearchIntentClassifyCreateBodyAvailableGroupTypesItemMax = 100

export const mlInferenceSearchIntentClassifyCreateBodyAvailableGroupTypesMax = 64

export const mlInferenceSearchIntentClassifyCreateBodySceneRegExp = new RegExp('^[A-Za-z0-9_-]{1,64}$')

export const MlInferenceSearchIntentClassifyCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .string()
        .max(mlInferenceSearchIntentClassifyCreateBodyQueryMax)
        .describe('What the person typed into the filter picker search box.'),
    active_group_type: zod
        .string()
        .max(mlInferenceSearchIntentClassifyCreateBodyActiveGroupTypeMax)
        .describe('The picker tab that is open, as a taxonomic group type such as event_properties.'),
    available_group_types: zod
        .array(zod.string().max(mlInferenceSearchIntentClassifyCreateBodyAvailableGroupTypesItemMax))
        .max(mlInferenceSearchIntentClassifyCreateBodyAvailableGroupTypesMax)
        .describe('The taxonomic group types the picker shows. The answer is always one of these, or null.'),
    scene: zod
        .string()
        .regex(mlInferenceSearchIntentClassifyCreateBodySceneRegExp)
        .nullish()
        .describe('The id of the scene the picker is open in, such as Insight or Replay.'),
})

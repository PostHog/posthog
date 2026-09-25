/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `noul` - Yes or no
 * * `choice` - Multiple choice
 * * `score` - Rating scale
 */
export type DecisionQuestionTypeEnumApi = (typeof DecisionQuestionTypeEnumApi)[keyof typeof DecisionQuestionTypeEnumApi]

export const DecisionQuestionTypeEnumApi = {
    Noul: 'noul',
    Choice: 'choice',
    Score: 'score',
} as const

/**
 * For a multiple choice question, the options keyed by name. For a rating question, the scale labels in order from lowest to highest, at least two. Omitted for a yes/no question.
 */
export type DecisionQuestionApiCriteria = { [key: string]: string } | string[]

export interface DecisionQuestionApi {
    /** What kind of answer to produce: a yes/no probability, one of the given options, or a rating.
     *
     * * `noul` - Yes or no
     * * `choice` - Multiple choice
     * * `score` - Rating scale */
    type: DecisionQuestionTypeEnumApi
    /**
     * The question to ask about the state, phrased for the model.
     * @maxLength 2000
     */
    instructions: string
    /** For a multiple choice question, the options keyed by name. For a rating question, the scale labels in order from lowest to highest, at least two. Omitted for a yes/no question. */
    criteria?: DecisionQuestionApiCriteria
}

/**
 * The questions to ask, keyed by an id of your choice, at most 32 per request. Answers come back under the same ids.
 */
export type DecideRequestApiQuestions = { [key: string]: DecisionQuestionApi }

export interface DecideRequestApi {
    /**
     * The text the questions are about, for example a support ticket or a session summary.
     * @maxLength 65536
     */
    state: string
    /** The questions to ask, keyed by an id of your choice, at most 32 per request. Answers come back under the same ids. */
    questions: DecideRequestApiQuestions
    /**
     * The decision model to ask, as a gateway model id.
     * @maxLength 200
     */
    model?: string
}

/**
 * For multiple choice and rating questions, the probability of each option.
 * @nullable
 */
export type DecisionAnswerApiProbabilities = { [key: string]: number } | null

export interface DecisionAnswerApi {
    /** The question type answered.
     *
     * * `noul` - Yes or no
     * * `choice` - Multiple choice
     * * `score` - Rating scale */
    type: DecisionQuestionTypeEnumApi
    /**
     * For a yes/no question, the probability of yes.
     * @nullable
     */
    probability: number | null
    /**
     * For a multiple choice question, the option chosen.
     * @nullable
     */
    choice: string | null
    /**
     * For a rating question, the expected rating.
     * @nullable
     */
    score: number | null
    /**
     * How far the chosen option stands out from the rest, from 0 (a coin flip) to 1.
     * @nullable
     */
    confidence: number | null
    /**
     * For multiple choice and rating questions, the probability of each option.
     * @nullable
     */
    probabilities: DecisionAnswerApiProbabilities
}

/**
 * One answer per question, under the ids the request used.
 */
export type DecideResponseApiAnswers = { [key: string]: DecisionAnswerApi }

export interface DecideResponseApi {
    /** The model that answered, as the serving host names it. */
    model: string
    /** One answer per question, under the ids the request used. */
    answers: DecideResponseApiAnswers
    /** Tokens the model read, which is what the request is billed on. */
    input_tokens: number
    /**
     * Time the model spent answering, if reported.
     * @nullable
     */
    latency_ms: number | null
}

export interface SearchIntentRequestApi {
    /**
     * What the person typed into the filter picker search box.
     * @maxLength 200
     */
    query: string
    /**
     * The picker tab that is open, as a taxonomic group type such as event_properties.
     * @maxLength 100
     */
    active_group_type: string
    /**
     * The taxonomic group types the picker shows. The answer is always one of these, or null.
     * @maxItems 64
     * @items.maxLength 100
     */
    available_group_types: string[]
    /**
     * The id of the scene the picker is open in, such as Insight or Replay.
     * @nullable
     * @pattern ^[A-Za-z0-9_-]{1,64}$
     */
    scene?: string | null
}

/**
 * * `rule` - Matched a value pattern
 * * `model` - Asked the decision model
 * * `skipped` - Not classified
 */
export type SearchIntentSourceEnumApi = (typeof SearchIntentSourceEnumApi)[keyof typeof SearchIntentSourceEnumApi]

export const SearchIntentSourceEnumApi = {
    Rule: 'rule',
    Model: 'model',
    Skipped: 'skipped',
} as const

export interface SearchIntentResponseApi {
    /**
     * The taxonomic group type the search most likely belongs to, or null if it was not classified.
     * @nullable
     */
    group_type: string | null
    /** How far the chosen group stands out from the rest, from 0 (a coin flip) to 1. */
    confidence: number
    /** Whether the confidence is high enough to act on, for example to suggest a different tab. */
    is_confident: boolean
    /** Whether the picker should suggest switching from the open tab to group_type. */
    suggests_switch: boolean
    /** How the answer was found: a value pattern, the decision model, or not at all.
     *
     * * `rule` - Matched a value pattern
     * * `model` - Asked the decision model
     * * `skipped` - Not classified */
    method: SearchIntentSourceEnumApi
}

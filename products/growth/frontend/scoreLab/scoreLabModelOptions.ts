// Fallback for the model select when GET /api/growth_score_lab/models/ errors: mirrors
// GATEWAY_MODEL_CHOICES in products/growth/backend/enrichment/lab.py. There's no generated
// enum to derive this from any more (model is a free string validated server-side), so keep
// this list in sync with the backend by hand, same as scoreLabInputFields.ts.
export const SCORE_LAB_FALLBACK_MODELS: string[] = [
    'gpt-5.2',
    'gpt-5.2-pro',
    'gpt-5.1',
    'gpt-5',
    'gpt-5-mini',
    'gpt-5-nano',
    'gpt-4.1',
    'gpt-4.1-mini',
    'claude-fable-5',
    'claude-opus-4-8',
    'claude-sonnet-5',
    'claude-haiku-4-5',
]

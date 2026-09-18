import { PROVIDER_BY_RUNTIME_ADAPTER } from './modelCatalog.generated'

/**
 * The form a model id is looked up under.
 *
 * The LLM gateway serves some models both bare and provider-qualified (`openai/gpt-5.6-sol`), and a stored run or
 * workflow config may carry either. Folding the two together is what stops one model from having two answers
 * depending on which surface asked. Only the provider prefixes this catalog knows are stripped, so ids that carry a
 * slash of their own (`@cf/zai-org/glm-5.2`) survive intact.
 *
 * The hand-written half of the catalog, kept beside the generated data the way the desktop app keeps
 * `model-catalog.ts` — the generator emits data only, so each language writes the lookup once.
 */
export function normalizeModelId(modelId: string): string {
    const normalized = modelId.trim().toLowerCase()
    for (const provider of Object.values(PROVIDER_BY_RUNTIME_ADAPTER)) {
        const prefix = `${provider}/`
        if (normalized.startsWith(prefix)) {
            return normalized.slice(prefix.length)
        }
    }
    return normalized
}

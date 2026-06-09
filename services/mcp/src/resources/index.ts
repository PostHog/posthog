import type { ResourceManifest } from './manifest-types'
import { fetchContextMillResources, filterValidEntries, loadManifestFromArchive } from './internals'

export { fetchContextMillResources, filterValidEntries, loadManifestFromArchive }

export async function getPromptsFromManifest(): Promise<ResourceManifest['resources']['prompts']> {
    return []
}

import { RESOURCE_MIME_TYPE } from '@modelcontextprotocol/ext-apps/server'
import type {
    GetPromptResult,
    ListPromptsResult,
    ListResourcesResult,
    ReadResourceResult,
    Resource,
    TextResourceContents,
} from '@modelcontextprotocol/sdk/types.js'

import { getManifest, getResourceText } from '@/resources/kv-store'
import type { ContextMillResource } from '@/resources/manifest-types'
import { buildAppStubHtml } from '@/resources/ui-apps'
import { UI_APPS } from '@/resources/ui-apps.generated'
import type { Env } from '@/tools/types'

export class ResourceCatalog {
    private readonly env: Env

    private resources: Resource[] = []
    /**
     * For UI apps and prompts we materialize the text at warmup because it's
     * generated locally and cheap. Context-mill resources are resolved lazily
     * via {@link getResourceText} on read; only their metadata lives in this
     * map, keyed by URI, so the Worker doesn't pin the full skill catalog in
     * heap.
     */
    private contextMillEntriesByUri = new Map<string, ContextMillResource>()
    private contextMillVersion: string | undefined
    private uiAppReadEntries = new Map<string, TextResourceContents>()
    private allResources: Resource[] = []
    private contextMillData: readonly ContextMillResource[] = []
    private uiAppResources: Resource[] = []

    constructor(env: Env) {
        this.env = env
    }

    get contextMillEntries(): readonly ContextMillResource[] {
        return this.contextMillData
    }

    async warmup(): Promise<void> {
        await Promise.all([this.warmupResources(), this.warmupUiApps()])
        this.allResources = [...this.resources, ...this.uiAppResources]
    }

    getResourcesList(): ListResourcesResult {
        return { resources: this.allResources }
    }

    async readResource(params: Record<string, unknown> | undefined): Promise<ReadResourceResult> {
        const uri = (params?.uri as string) ?? ''
        const uiEntry = this.uiAppReadEntries.get(uri)
        if (uiEntry) {
            return {
                contents: [
                    {
                        uri: uiEntry.uri,
                        mimeType: uiEntry.mimeType,
                        text: uiEntry.text,
                        ...(uiEntry._meta ? { _meta: uiEntry._meta } : {}),
                    },
                ],
            }
        }
        const cmEntry = this.contextMillEntriesByUri.get(uri)
        if (cmEntry && this.contextMillVersion) {
            const text = await getResourceText(this.env, this.contextMillVersion, cmEntry)
            return {
                contents: [
                    {
                        uri,
                        mimeType: cmEntry.resource.mimeType,
                        text,
                    },
                ],
            }
        }
        return { contents: [] }
    }

    // No prompts are currently served. The dispatcher still needs these so
    // `prompts/list` / `prompts/get` return a well-formed empty response rather
    // than 404ing — wire up a real source here when prompts are reintroduced.
    getPromptsList(): ListPromptsResult {
        return { prompts: [] }
    }

    getPrompt(_params: Record<string, unknown> | undefined): GetPromptResult {
        return { messages: [] }
    }

    private async warmupResources(): Promise<void> {
        try {
            const manifest = await getManifest(this.env)
            this.contextMillVersion = manifest.version
            this.contextMillData = manifest.resources

            for (const entry of this.contextMillData) {
                this.resources.push({
                    name: entry.name,
                    uri: entry.uri,
                    mimeType: entry.resource.mimeType,
                    description: entry.resource.description,
                })
                this.contextMillEntriesByUri.set(entry.uri, entry)
            }
        } catch (error) {
            console.error('[ResourceCatalog] Failed to pre-load context-mill resources:', error)
        }
    }

    private async warmupUiApps(): Promise<void> {
        const baseUrl = this.env.MCP_APPS_BASE_URL
        if (!baseUrl) {
            return
        }

        const analyticsBaseUrl = this.env.POSTHOG_MCP_APPS_ANALYTICS_BASE_URL

        for (const app of UI_APPS) {
            const html = buildAppStubHtml(app.appDir, baseUrl)

            const uiMetadata: Record<string, unknown> = {}
            const resourceDomains = [baseUrl]
            const connectDomains: string[] = []
            if (analyticsBaseUrl) {
                connectDomains.push(analyticsBaseUrl)
                resourceDomains.push(analyticsBaseUrl)
            }
            uiMetadata.csp = { connectDomains, resourceDomains }

            this.uiAppResources.push({
                name: app.name,
                uri: app.uri,
                mimeType: RESOURCE_MIME_TYPE,
                description: app.description,
            })
            this.uiAppReadEntries.set(app.uri, {
                uri: app.uri,
                mimeType: RESOURCE_MIME_TYPE,
                text: html,
                _meta: { ui: uiMetadata },
            })
        }
    }
}

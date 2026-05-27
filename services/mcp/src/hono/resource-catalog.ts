import { RESOURCE_MIME_TYPE } from '@modelcontextprotocol/ext-apps/server'
import type {
    GetPromptResult,
    ListPromptsResult,
    ListResourcesResult,
    Prompt,
    ReadResourceResult,
    Resource,
    TextResourceContents,
} from '@modelcontextprotocol/sdk/types.js'

import { getPromptsFromManifest } from '@/resources'
import { fetchAndExtractEntries } from '@/resources/internals'
import { buildAppStubHtml } from '@/resources/ui-apps'
import { UI_APPS } from '@/resources/ui-apps.generated'
import type { Env } from '@/tools/types'

import { ContextMillResourceCache, type SlimManifestEntry } from './cache/ContextMillResourceCache'
import type { RedisLike } from './cache/RedisCache'

export class ResourceCatalog {
    private readonly env: Env
    private readonly contextMillCache: ContextMillResourceCache | undefined

    private resources: Resource[] = []
    private prompts: Prompt[] = []
    private promptsByName = new Map<string, GetPromptResult>()
    private uiAppResources: Resource[] = []
    private uiAppReadEntries = new Map<string, TextResourceContents>()
    private allResources: Resource[] = []
    private contextMillEntriesByUri = new Map<string, SlimManifestEntry>()

    constructor(env: Env, redis?: RedisLike) {
        this.env = env
        this.contextMillCache = redis ? new ContextMillResourceCache(redis) : undefined
    }

    get contextMillEntries(): readonly SlimManifestEntry[] {
        return Array.from(this.contextMillEntriesByUri.values())
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

        const slimEntry = this.contextMillEntriesByUri.get(uri)
        if (!slimEntry || !this.contextMillCache) {
            return { contents: [] }
        }
        const body = await this.contextMillCache.readBody(uri)
        if (!body) {
            // Body has aged out (resource removed upstream + TTL elapsed) or
            // was evicted. Ack the removal and let the slim manifest catch up
            // on the next natural refresh; the client's context window has
            // already cached what it needs from the prior resources/list.
            return { contents: [] }
        }
        return {
            contents: [
                {
                    uri: slimEntry.uri,
                    mimeType: body.mimeType,
                    text: body.text,
                },
            ],
        }
    }

    getPromptsList(): ListPromptsResult {
        return { prompts: this.prompts }
    }

    getPrompt(params: Record<string, unknown> | undefined): GetPromptResult {
        const name = (params?.name as string) ?? ''
        const entry = this.promptsByName.get(name)
        if (!entry) {
            return { messages: [] }
        }
        return { messages: entry.messages }
    }

    private async refreshContextMill(): Promise<void> {
        if (!this.contextMillCache) {
            return
        }
        const localUrlRaw = (this.env as Record<string, string | undefined>)?.POSTHOG_MCP_LOCAL_SKILLS_URL
        const localUrl = localUrlRaw && localUrlRaw.trim() !== '' ? localUrlRaw : undefined
        const slim = await this.contextMillCache.loadOrRefresh(() => fetchAndExtractEntries(localUrl))

        const nextEntriesByUri = new Map<string, SlimManifestEntry>()
        const nextResources: Resource[] = []
        for (const entry of slim.entries) {
            nextEntriesByUri.set(entry.uri, entry)
            nextResources.push({
                name: entry.name,
                uri: entry.uri,
                mimeType: entry.mimeType,
                description: entry.description,
            })
        }
        this.contextMillEntriesByUri = nextEntriesByUri
        this.resources = nextResources
        this.allResources = [...this.resources, ...this.uiAppResources]
    }

    private async warmupResources(): Promise<void> {
        try {
            await this.refreshContextMill()
        } catch (error) {
            console.error('[ResourceCatalog] Failed to pre-load context-mill resources:', error)
        }

        try {
            const manifestPrompts = await getPromptsFromManifest()
            for (const prompt of manifestPrompts) {
                this.prompts.push({
                    name: prompt.name,
                    title: prompt.title,
                    description: prompt.description,
                })
                this.promptsByName.set(prompt.name, { messages: prompt.messages as GetPromptResult['messages'] })
            }
        } catch (error) {
            console.error('[ResourceCatalog] Failed to pre-load prompts:', error)
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

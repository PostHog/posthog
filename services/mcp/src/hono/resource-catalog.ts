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
import { buildAppStubHtml, buildUiAppResourceMeta } from '@/resources/ui-apps'
import { UI_APPS } from '@/resources/ui-apps.generated'
import type { Env } from '@/tools/types'

import {
    ContextMillResourceCache,
    type ContextMillCacheResult,
    type SlimManifestEntry,
} from './cache/ContextMillResourceCache'
import type { RedisLike } from './cache/RedisCache'
import {
    contextMillManifestEntries,
    contextMillRevalidationDurationSeconds,
    contextMillRevalidationsTotal,
} from './metrics'

export type ContextMillRevalidationSource = 'warmup' | 'initialize'

export class ResourceCatalog {
    private readonly env: Env
    private readonly contextMillCache: ContextMillResourceCache

    private resources: Resource[] = []
    private prompts: Prompt[] = []
    private promptsByName = new Map<string, GetPromptResult>()
    private uiAppResources: Resource[] = []
    private uiAppReadEntries = new Map<string, TextResourceContents>()
    private allResources: Resource[] = []
    private contextMillEntriesByUri = new Map<string, SlimManifestEntry>()

    constructor(env: Env, redis: RedisLike) {
        this.env = env
        const localUrl = this.contextMillLocalUrl()
        this.contextMillCache = new ContextMillResourceCache(redis, localUrl ? { localUrl } : {})
    }

    get contextMillEntries(): readonly SlimManifestEntry[] {
        return Array.from(this.contextMillEntriesByUri.values())
    }

    async revalidateContextMillResources(source: ContextMillRevalidationSource): Promise<void> {
        const stop = contextMillRevalidationDurationSeconds.startTimer({ source })
        try {
            const result = await this.refreshContextMill()
            contextMillRevalidationsTotal.inc({ source, status: 'success', result })
            stop({ source, status: 'success' })
        } catch (error) {
            contextMillRevalidationsTotal.inc({ source, status: 'error', result: 'error' })
            stop({ source, status: 'error' })
            console.error('[ResourceCatalog] Failed to revalidate context-mill resources:', error)
        }
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
        if (!slimEntry) {
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

    private async refreshContextMill(): Promise<ContextMillCacheResult> {
        const { manifest: slim, result } = await this.contextMillCache.loadOrRefresh()

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
        contextMillManifestEntries.set(slim.entries.length)
        return result
    }

    private contextMillLocalUrl(): string | undefined {
        const localUrlRaw = (this.env as Record<string, string | undefined>)?.POSTHOG_MCP_LOCAL_SKILLS_URL
        return localUrlRaw && localUrlRaw.trim() !== '' ? localUrlRaw : undefined
    }

    private async warmupResources(): Promise<void> {
        await this.revalidateContextMillResources('warmup')

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
            const meta = buildUiAppResourceMeta(baseUrl, analyticsBaseUrl)

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
                _meta: meta,
            })
        }
    }
}

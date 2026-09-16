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
import { buildAppStubHtml, buildUiAppResourceMeta, resolveUiAppsBaseUrl } from '@/resources/ui-apps'
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

export type ContextMillRevalidationSource = 'warmup' | 'initialize' | 'discover'

export class ResourceCatalog {
    private readonly env: Env
    private readonly contextMillCache: ContextMillResourceCache

    private resources: Resource[] = []
    private prompts: Prompt[] = []
    private promptsByName = new Map<string, GetPromptResult>()
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
        await this.warmupResources()
    }

    getResourcesList(publicOrigin?: string): ListResourcesResult {
        return { resources: [...this.resources, ...this.uiAppResources(publicOrigin)] }
    }

    async readResource(
        params: Record<string, unknown> | undefined,
        publicOrigin?: string
    ): Promise<ReadResourceResult> {
        const uri = (params?.uri as string) ?? ''
        const uiEntry = this.uiAppReadEntry(uri, publicOrigin)
        if (uiEntry) {
            return { contents: [uiEntry] }
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

    private uiAppsBaseUrl(publicOrigin?: string): string | undefined {
        return resolveUiAppsBaseUrl(publicOrigin, this.env.MCP_APPS_BASE_URL)
    }

    private uiAppResources(publicOrigin?: string): Resource[] {
        const baseUrl = this.uiAppsBaseUrl(publicOrigin)
        if (!baseUrl) {
            return []
        }
        const meta = buildUiAppResourceMeta(baseUrl, this.env.POSTHOG_MCP_APPS_ANALYTICS_BASE_URL)
        return UI_APPS.map((app) => ({
            name: app.name,
            uri: app.uri,
            mimeType: RESOURCE_MIME_TYPE,
            description: app.description,
            _meta: meta,
        }))
    }

    private uiAppReadEntry(uri: string, publicOrigin?: string): TextResourceContents | undefined {
        const app = UI_APPS.find((candidate) => candidate.uri === uri)
        const baseUrl = app ? this.uiAppsBaseUrl(publicOrigin) : undefined
        if (!app || !baseUrl) {
            return undefined
        }
        return {
            uri: app.uri,
            mimeType: RESOURCE_MIME_TYPE,
            text: buildAppStubHtml(app.appDir, baseUrl),
            _meta: buildUiAppResourceMeta(baseUrl, this.env.POSTHOG_MCP_APPS_ANALYTICS_BASE_URL),
        }
    }
}

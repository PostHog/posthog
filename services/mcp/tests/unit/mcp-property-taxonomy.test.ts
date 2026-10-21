import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import { PostHogMCPAnalyticsProperty } from '@posthog/mcp-analytics'

const REPO_ROOT = fileURLToPath(new URL('../../../../', import.meta.url))
const MCP_SOURCE = join(REPO_ROOT, 'services/mcp/src')
const TAXONOMY_PATH = join(REPO_ROOT, 'frontend/src/taxonomy/core-filter-definitions-by-group.json')

// These properties need taxonomy work. This list keeps existing gaps explicit and rejects new gaps.
const KNOWN_UNREGISTERED_MCP_PROPERTIES = new Set([
    '$mcp_skill_lookup_miss_kind',
    '$mcp_app_name',
    '$mcp_app_version',
    '$mcp_app_instance_id',
    '$mcp_feedback_details',
    '$mcp_feedback_friction_points',
    '$mcp_feedback_sentiment',
    '$mcp_feedback_suggested_improvement',
    '$mcp_feedback_summary',
    '$mcp_feedback_task_completed',
    '$mcp_feedback_tool',
    '$mcp_feedback_type',
])

function typescriptFiles(directory: string): string[] {
    return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
        const path = join(directory, entry.name)
        if (entry.isDirectory()) {
            return typescriptFiles(path)
        }
        return entry.name.endsWith('.ts') || entry.name.endsWith('.tsx') ? [path] : []
    })
}

function stampedServerProperties(): Set<string> {
    const properties = new Set<string>()
    for (const path of typescriptFiles(MCP_SOURCE)) {
        for (const match of readFileSync(path, 'utf8').matchAll(/\$mcp_[a-z0-9_]+(?=\s*:)/g)) {
            properties.add(match[0])
        }
    }
    return properties
}

function registeredProperties(): Set<string> {
    const taxonomy = JSON.parse(readFileSync(TAXONOMY_PATH, 'utf8')) as {
        event_properties: Record<string, unknown>
    }
    return new Set(Object.keys(taxonomy.event_properties))
}

describe('MCP property taxonomy', () => {
    it('registers properties from the server and SDK', () => {
        const stamped = stampedServerProperties()
        for (const property of Object.values(PostHogMCPAnalyticsProperty)) {
            if (property.startsWith('$mcp_')) {
                stamped.add(property)
            }
        }
        expect(stamped.size).toBeGreaterThan(20)

        const registered = registeredProperties()
        const unregistered = [...stamped].filter(
            (property) => !registered.has(property) && !KNOWN_UNREGISTERED_MCP_PROPERTIES.has(property)
        )
        expect(unregistered.sort()).toEqual([])

        const staleExceptions = [...KNOWN_UNREGISTERED_MCP_PROPERTIES].filter((property) => registered.has(property))
        expect(staleExceptions.sort()).toEqual([])
    })
})

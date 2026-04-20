/**
 * Formats the brief schema output for a tool — JSON with params and
 * pre-resolved types, but without the (potentially huge) description.
 */

import type { CliToolManifest } from './manifest.js'

export function briefSchema(toolName: string, tool: CliToolManifest): Record<string, unknown> {
    const schema: Record<string, unknown> = {
        name: toolName,
        title: tool.title,
        method: tool.method,
        path: tool.path,
        category: tool.category,
        scopes: tool.scopes,
        annotations: tool.annotations,
    }
    if (tool.query_kind) {
        schema.query_kind = tool.query_kind
        schema.params = tool.query_schema ?? []
        if (tool.types && Object.keys(tool.types).length > 0) {
            schema.types = tool.types
        }
    } else {
        schema.params = tool.params
        if (tool.soft_delete) {
            schema.soft_delete = tool.soft_delete
        }
    }
    return schema
}

export function fullSchema(toolName: string, tool: CliToolManifest): Record<string, unknown> {
    return {
        ...briefSchema(toolName, tool),
        description: tool.description,
    }
}

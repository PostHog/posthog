import './theme.css'

import type { StoryFn } from '@storybook/react'
import type { ReactElement } from 'react'

/**
 * MCP Apps host CSS variables — simulates what the host injects via useHostStyleVariables.
 * See: https://github.com/modelcontextprotocol/ext-apps/blob/main/src/spec.types.ts
 *
 * The MCP UI runtime bridges these onto Quill tokens (--background, --foreground, etc.)
 * via services/mcp/src/ui-apps/styles/tailwind.css. In Storybook we don't run that
 * bridge, so the theme.css beside this file maps the Quill class names that
 * primitives use directly onto the ext-apps host vars.
 */
const mcpAppsCssVariables: Record<string, string> = {
    // Background
    '--color-background-primary': '#ffffff',
    '--color-background-secondary': '#f9fafb',
    '--color-background-tertiary': '#f2f4f7',
    '--color-background-inverse': '#101828',
    '--color-background-ghost': 'transparent',
    '--color-background-info': '#eff6ff',
    '--color-background-danger': '#fef2f2',
    '--color-background-success': '#f0fdf4',
    '--color-background-warning': '#fffbeb',
    '--color-background-disabled': '#f2f4f7',
    // Text
    '--color-text-primary': '#101828',
    '--color-text-secondary': '#6b7280',
    '--color-text-tertiary': '#9ca3af',
    '--color-text-inverse': '#ffffff',
    '--color-text-ghost': '#6b7280',
    '--color-text-info': '#2563eb',
    '--color-text-danger': '#dc2626',
    '--color-text-success': '#059669',
    '--color-text-warning': '#d97706',
    '--color-text-disabled': '#9ca3af',
    // Border
    '--color-border-primary': '#e5e7eb',
    '--color-border-secondary': '#d1d5db',
    '--color-border-tertiary': '#f2f4f7',
    '--color-border-inverse': '#374151',
    '--color-border-ghost': 'transparent',
    '--color-border-info': '#bfdbfe',
    '--color-border-danger': '#fecaca',
    '--color-border-success': '#bbf7d0',
    '--color-border-warning': '#fde68a',
    '--color-border-disabled': '#e5e7eb',
    // Fonts
    '--font-sans': "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
    '--font-mono': "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace",
    '--font-weight-normal': '400',
    '--font-weight-medium': '500',
    '--font-weight-semibold': '600',
    '--font-weight-bold': '700',
}

/** Decorator that injects MCP Apps host CSS variables onto the story root. */
export function McpThemeDecorator(Story: StoryFn): ReactElement {
    return (
        <div
            style={
                {
                    ...mcpAppsCssVariables,
                    fontFamily: 'var(--font-sans)',
                    color: 'var(--color-text-primary)',
                    backgroundColor: 'var(--color-background-primary)',
                    padding: '1.5rem',
                    maxWidth: 720,
                    minHeight: 200,
                } as React.CSSProperties
            }
        >
            <Story />
        </div>
    )
}

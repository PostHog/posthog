// The registry alone, for a product that claims its tool names at app boot. `api/tools` also
// carries the card components, whose markdown, diff and code-highlighting dependencies must stay
// off the boot path that every page, including /login, downloads.
export { toolRegistry, lookupToolRenderer, registerToolRenderers } from '../components/tool/toolRegistry'
export type {
    ToolRendererProps,
    ToolRegistryEntry,
    ResolvedToolRegistryEntry,
    ToolRegistry,
} from '../components/tool/toolRegistry'

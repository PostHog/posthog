// Thin re-export: `resolveToolCall` now lives in the headless `utils/` lane so `api/logics` + `hooks/*`
// can reach it without importing `components/*`. This shim keeps any external `components/tool/toolResolver`
// importer working. Change the resolver in `utils/toolResolver.ts`, not here.
export {
    resolveToolCall,
    resolveToolKey,
    getClaudeCodeMeta,
    extractClaudeToolName,
    type ResolvableToolCall,
    type ResolvedToolCall,
    type ResolvedToolKey,
} from '../../utils/toolResolver'

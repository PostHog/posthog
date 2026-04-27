import ts from 'typescript'

/**
 * Strips TypeScript type syntax from a snippet and returns runnable JavaScript.
 * This is NOT typechecking — it's a pure syntactic transform (~5 ms).
 * Type errors fall through to runtime; the agent retries.
 */
export function transpileSnippet(snippet: string): string {
    const result = ts.transpileModule(snippet, {
        compilerOptions: {
            target: ts.ScriptTarget.ES2022,
            module: ts.ModuleKind.None,
            isolatedModules: true,
            esModuleInterop: true,
            allowSyntheticDefaultImports: true,
        },
        reportDiagnostics: false,
    })
    return result.outputText
}

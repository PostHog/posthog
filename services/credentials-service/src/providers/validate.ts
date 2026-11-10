import { providerSpecSchema, type ProviderSpec } from './schema'

export class ProviderSpecError extends Error {
    constructor(readonly problems: string[]) {
        super(`invalid provider specs:\n${problems.join('\n')}`)
        this.name = 'ProviderSpecError'
    }
}

/**
 * Check every spec at boot, so a bad spec stops the deploy instead of failing the first
 * connection that uses it. Throws with every problem, not only the first.
 */
export function validateProviderSpecs(specs: readonly ProviderSpec[]): void {
    const problems: string[] = []
    const seen = new Set<string>()
    specs.forEach((spec, index) => {
        const name = typeof spec.kind === 'string' ? spec.kind : `#${index}`
        if (seen.has(spec.kind)) {
            problems.push(`${name}: the kind is registered twice`)
        }
        seen.add(spec.kind)
        const result = providerSpecSchema.safeParse(spec)
        if (!result.success) {
            for (const issue of result.error.issues) {
                problems.push(`${name}: ${issue.path.join('.') || '(spec)'}: ${issue.message}`)
            }
        }
    })
    if (problems.length > 0) {
        throw new ProviderSpecError(problems)
    }
}

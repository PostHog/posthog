import { getContext } from 'kea'

import { integrationsGithubRepositoryAccessRetrieve } from 'products/integrations/frontend/generated/api'

interface Probe {
    promise: Promise<boolean>
    controller: AbortController
    readers: number
    expiresAt: number
}

export interface GithubAccessProbe {
    promise: Promise<boolean>
    release: () => void
}

export class GithubAccessProbes {
    private static contexts = new WeakMap<object, GithubAccessProbes>()
    private probes = new Map<string, Probe>()

    static forContext(): GithubAccessProbes {
        const context = getContext()
        let probes = this.contexts.get(context)
        if (!probes) {
            probes = new GithubAccessProbes()
            this.contexts.set(context, probes)
        }
        return probes
    }

    invalidate(projectId: string): void {
        for (const key of this.probes.keys()) {
            if (key.startsWith(`${projectId}/`)) {
                this.probes.delete(key)
            }
        }
    }

    acquire(projectId: string, integrationId: number, repository?: string): GithubAccessProbe {
        for (const [key, probe] of this.probes) {
            if (probe.expiresAt <= Date.now()) {
                this.probes.delete(key)
            }
        }
        const key = `${projectId}/${integrationId}/${repository ?? ''}`
        let probe = this.probes.get(key)
        if (!probe) {
            const controller = new AbortController()
            const timeout = setTimeout(() => controller.abort(), 30_000)
            probe = {
                controller,
                readers: 0,
                expiresAt: Infinity,
                promise: integrationsGithubRepositoryAccessRetrieve(
                    projectId,
                    integrationId,
                    repository ? { repository } : undefined,
                    { signal: controller.signal }
                )
                    .then(({ available }) => available)
                    .finally(() => clearTimeout(timeout)),
            }
            const pending = probe
            void pending.promise.then(
                () => {
                    pending.expiresAt = Date.now() + 30_000
                },
                () => {
                    if (this.probes.get(key) === pending) {
                        this.probes.delete(key)
                    }
                }
            )
            this.probes.set(key, probe)
        }
        const acquired = probe
        acquired.readers++
        let released = false
        return {
            promise: acquired.promise,
            release: () => {
                if (released) {
                    return
                }
                released = true
                acquired.readers--
                if (acquired.readers === 0 && acquired.expiresAt === Infinity) {
                    acquired.controller.abort()
                    if (this.probes.get(key) === acquired) {
                        this.probes.delete(key)
                    }
                }
            },
        }
    }
}

// Where the service reads the Kubernetes Secret from. A source yields the WHOLE secret at one
// version, and the server applies that one snapshot to both the signing keys and the secrets.
// So a revocation and a rotation made in one edit of the secret land together.

import { KubernetesSecretSource } from './kubernetes'
import type { Config, SecretSourceKind } from './lib/config'
import { readMount } from './mount'

/** Every entry in the secret, as one version of it held them. */
export interface SecretSnapshot {
    values: Record<string, string>
    /** The source's own version label, e.g. a resourceVersion. For logs only. */
    revision: string | null
}

/** Receives a snapshot, or null when the source has nothing it can serve. */
export type SnapshotListener = (snapshot: SecretSnapshot | null) => void

export interface SecretSource {
    readonly kind: SecretSourceKind
    /** Names the secret in logs and error messages. Never a value. */
    readonly description: string
    /** Read the whole secret once. Null when it cannot be read. */
    read(): Promise<SecretSnapshot | null>
    /** Push later changes to `listener` until `stop()`. A source without a watch pushes nothing. */
    watch(listener: SnapshotListener): void
    stop(): void
}

/** The mounted Secret volume. Kubelet refreshes it, so there is nothing to watch. */
export class DirectorySecretSource implements SecretSource {
    readonly kind = 'directory'

    constructor(private readonly dir: string) {}

    get description(): string {
        return this.dir
    }

    async read(): Promise<SecretSnapshot | null> {
        const values = await readMount(this.dir)
        return values ? { values, revision: null } : null
    }

    watch(): void {}

    stop(): void {}
}

export function createSecretSource(config: Config): SecretSource {
    return config.kubernetes
        ? new KubernetesSecretSource(config.kubernetes)
        : new DirectorySecretSource(config.mountDir)
}

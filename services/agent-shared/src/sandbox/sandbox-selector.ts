/**
 * Pick a sandbox pool impl from env. Single switch point so the runner stays
 * agnostic. Prod must explicitly pick `modal` (or `docker` for local dev with
 * isolation); `in-process` is **not** a valid choice at this boundary —
 * harness + per-package tests instantiate `InProcessSandboxPool` directly when
 * they want the unisolated path.
 */

import { SandboxPool } from './sandbox'
import { DockerSandboxPool } from './sandbox-docker'
import { ModalSandboxPool } from './sandbox-modal'

export type SandboxBackend = 'docker' | 'modal'

/**
 * Image override resolution. Backend-specific env wins; otherwise the shared
 * `SANDBOX_HOST_IMAGE` (canonical `posthog-agent-sandbox-host` reference, pinned
 * by SHA in prod) applies to both. Unset → backend default.
 */
function resolveImage(backendSpecific: string | undefined): string | undefined {
    return backendSpecific ?? process.env.SANDBOX_HOST_IMAGE
}

export function selectSandboxPool(backend: SandboxBackend = pickFromEnv()): SandboxPool {
    switch (backend) {
        case 'docker':
            return new DockerSandboxPool({ image: resolveImage(process.env.SANDBOX_DOCKER_IMAGE) })
        case 'modal':
            // MODAL_TOKEN_ID + MODAL_TOKEN_SECRET are read directly from env
            // by the Modal SDK — no constructor opts needed.
            return new ModalSandboxPool({
                appName: process.env.MODAL_APP_NAME,
                image: resolveImage(process.env.SANDBOX_MODAL_IMAGE),
                region: process.env.MODAL_REGION,
            })
    }
}

function pickFromEnv(): SandboxBackend {
    const v = process.env.SANDBOX_BACKEND
    if (v === 'modal' || v === 'docker') {
        return v
    }
    throw new Error(
        `SANDBOX_BACKEND must be 'modal' (prod) or 'docker' (local). Got ${
            v === undefined ? '(unset)' : JSON.stringify(v)
        }. In-process sandbox is intentionally not selectable at this boundary — tests instantiate InProcessSandboxPool directly.`
    )
}

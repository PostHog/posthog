/**
 * Pick a sandbox pool impl from env. Single switch point so the runner stays
 * agnostic. `agent-tests-v2` overrides this to inject the in-process pool.
 */

import { SandboxPool } from './sandbox'
import { DockerSandboxPool } from './sandbox-docker'
import { InProcessSandboxPool } from './sandbox-inprocess'
import { ModalSandboxPool } from './sandbox-modal'

export type SandboxBackend = 'in-process' | 'docker' | 'modal'

export function selectSandboxPool(backend: SandboxBackend = pickFromEnv()): SandboxPool {
    switch (backend) {
        case 'in-process':
            return new InProcessSandboxPool()
        case 'docker':
            return new DockerSandboxPool({ image: process.env.SANDBOX_DOCKER_IMAGE })
        case 'modal':
            return new ModalSandboxPool({
                workspace: process.env.MODAL_WORKSPACE,
                token: process.env.MODAL_TOKEN,
            })
    }
}

function pickFromEnv(): SandboxBackend {
    const v = (process.env.SANDBOX_BACKEND ?? 'in-process') as SandboxBackend
    if (v !== 'in-process' && v !== 'docker' && v !== 'modal') {
        throw new Error(`unknown SANDBOX_BACKEND=${v}`)
    }
    return v
}

/**
 * Modal sandbox pool. Stub — interface conformant, implementation deferred.
 *
 * In production this will provision a Modal sandbox per session via the Modal
 * SDK / HTTP API, mount the compiled tool bundle, and dispatch via Modal's
 * function-call protocol. For now, the class exists so the runner can
 * conditionally select it via env config without code branching.
 */

import { AcquireOpts, Sandbox, SandboxPool } from './sandbox'

export class ModalSandboxPool implements SandboxPool {
    readonly kind = 'modal' as const

    constructor(_opts?: { workspace?: string; token?: string }) {
        // accept Modal config; not used by the stub
    }

    acquireForSession(_opts: AcquireOpts): Promise<Sandbox> {
        return Promise.reject(
            new Error(
                'Modal sandbox not implemented. Set SANDBOX_BACKEND=in-process or =docker, or implement ModalSandboxPool.'
            )
        )
    }

    release(_sessionId: string): Promise<void> {
        return Promise.resolve()
    }
}

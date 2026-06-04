/**
 * Unit tests for `selectSandboxPool` env-resolution. Covers the
 * `SANDBOX_HOST_IMAGE` shared fallback path that lets the chart set a single
 * image reference for both pools (Modal in prod, Docker in local dev) — and
 * the fail-fast behaviour when SANDBOX_BACKEND is missing or invalid.
 *
 * Construction of the actual pool classes is what we assert against; we
 * never poke into the Modal SDK or shell out to docker here.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { DockerSandboxPool } from './sandbox-docker'
import { ModalSandboxPool } from './sandbox-modal'
import { selectSandboxPool } from './sandbox-selector'

const ENV_KEYS = [
    'SANDBOX_BACKEND',
    'SANDBOX_DOCKER_IMAGE',
    'SANDBOX_MODAL_IMAGE',
    'SANDBOX_HOST_IMAGE',
    'MODAL_REGION',
]
const SAVED: Record<string, string | undefined> = {}

describe('selectSandboxPool', () => {
    beforeEach(() => {
        for (const k of ENV_KEYS) {
            SAVED[k] = process.env[k]
            delete process.env[k]
        }
    })
    afterEach(() => {
        for (const k of ENV_KEYS) {
            if (SAVED[k] === undefined) {
                delete process.env[k]
            } else {
                process.env[k] = SAVED[k]
            }
        }
    })

    it('throws a clear error when SANDBOX_BACKEND is unset', () => {
        expect(() => selectSandboxPool()).toThrow(/SANDBOX_BACKEND must be 'modal' \(prod\) or 'docker' \(local\)/)
    })

    it('throws when SANDBOX_BACKEND is set to an unsupported value', () => {
        process.env.SANDBOX_BACKEND = 'in-process'
        expect(() => selectSandboxPool()).toThrow(/SANDBOX_BACKEND must be 'modal' \(prod\) or 'docker' \(local\)/)
        expect(() => selectSandboxPool()).toThrow(/Got "in-process"/)
    })

    it('returns a DockerSandboxPool for SANDBOX_BACKEND=docker', () => {
        process.env.SANDBOX_BACKEND = 'docker'
        const pool = selectSandboxPool()
        expect(pool).toBeInstanceOf(DockerSandboxPool)
        expect(pool.kind).toBe('docker')
    })

    it('returns a ModalSandboxPool for SANDBOX_BACKEND=modal', () => {
        process.env.SANDBOX_BACKEND = 'modal'
        const pool = selectSandboxPool()
        expect(pool).toBeInstanceOf(ModalSandboxPool)
        expect(pool.kind).toBe('modal')
    })

    it('SANDBOX_HOST_IMAGE applies when no backend-specific override is set', () => {
        // Construction of the pools doesn't expose the image directly, so
        // we go through the explicit-backend overload and inspect the
        // resulting pool's behaviour via property paths the wiring path
        // touches. Each pool stores opts on a private field; reaching in
        // via `as any` is acceptable for a pure-shape test.
        process.env.SANDBOX_HOST_IMAGE = 'ghcr.io/posthog/posthog-agent-sandbox-host@sha256:abc'
        process.env.SANDBOX_BACKEND = 'modal'

        const modal = selectSandboxPool('modal') as unknown as { opts: { image?: string } }
        expect(modal.opts.image).toBe('ghcr.io/posthog/posthog-agent-sandbox-host@sha256:abc')

        const docker = selectSandboxPool('docker') as unknown as { image: string }
        // Docker pool stores the resolved image directly on `image`.
        expect(docker.image).toBe('ghcr.io/posthog/posthog-agent-sandbox-host@sha256:abc')
    })

    it('backend-specific env var overrides the shared SANDBOX_HOST_IMAGE', () => {
        process.env.SANDBOX_HOST_IMAGE = 'shared:default'
        process.env.SANDBOX_MODAL_IMAGE = 'modal-only:override'
        process.env.SANDBOX_DOCKER_IMAGE = 'docker-only:override'

        const modal = selectSandboxPool('modal') as unknown as { opts: { image?: string } }
        expect(modal.opts.image).toBe('modal-only:override')

        const docker = selectSandboxPool('docker') as unknown as { image: string }
        expect(docker.image).toBe('docker-only:override')
    })
})

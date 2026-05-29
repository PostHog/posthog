/**
 * MSW browser worker — registered by `<MswBootstrap />` on app mount.
 *
 * Lazy import so the worker setup only ships in dev / Storybook
 * bundles, not in the production app (the production app will hit
 * real PostHog / agent-ingress endpoints).
 */

import { setupWorker } from 'msw/browser'

import { handlers } from './handlers'

export const worker = setupWorker(...handlers)

/**
 * Registry of dynamic confirmation-message builders referenced by
 * `confirmation.builder` in a tool YAML.
 *
 * Builders run on the blocking path before the confirmation modal shows
 * up. Keep them quick and side-effect-free — they execute regardless of
 * whether the user accepts or declines.
 */

import type { Context } from './types'

export type ConfirmationBuilder<Params = Record<string, unknown>> = (
    params: Params,
    context: Context
) => string | Promise<string>

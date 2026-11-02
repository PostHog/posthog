import { dayjs } from 'lib/dayjs'

import { NodeKind } from '~/queries/schema/schema-general'

import type { ScannerFormValues } from './types'
import { DEFAULT_MODEL, DEFAULT_PROVIDER, OBSERVATION_CREDITS_BY_MODEL, defaultScannerName } from './types'

export function newScanner(teamName?: string | null): ScannerFormValues {
    const base = {
        id: 'new',
        enabled: true,
        tags: [] as string[],
        // Starts narrow: a wizard that opens on every recording at full rate quotes a scary first number.
        sampling_rate: 0.2,
        sampling_mode: 'balanced' as const,
        query: { kind: NodeKind.RecordingsQuery },
        provider: DEFAULT_PROVIDER,
        model: DEFAULT_MODEL,
        emits_signals: false,
        scanner_version: 1,
        last_swept_at: dayjs().toISOString(),
        created_at: dayjs().toISOString(),
        updated_at: dayjs().toISOString(),
        created_by: null,
        estimated_monthly_observations: null,
        // The server writes this on the first save.
        prompt_question: '',
        estimated_monthly_credits: null,
        estimated_at: null,
        // Seed price for the unsaved scanner; the server-computed value takes over after the first save.
        credits_per_observation: OBSERVATION_CREDITS_BY_MODEL[DEFAULT_MODEL],
        // An unsaved scanner has no object yet, so there's no effective access level for it —
        // create-time gating falls back to the resource-level default instead (see getReplayVisionEditDisabledReason).
        user_access_level: null,
        credits_this_month: 0,
        observations_this_month: 0,
        credit_limit: null,
        // Materialized here so toggling the limit on and off compares equal to this baseline again.
        credit_limit_enabled: false,
        free_only: false,
        // An unsaved scanner has no spend yet, so it can't have hit a limit it doesn't have.
        credits_used_against_limit: 0,
        limit_from_free_credits: false,
        limit_reached: false,
        sweep_throttle_factor: 1,
        dashboard_id: null,
        dashboard_suggested: false,
        filter_error: null,
    } as const

    return {
        ...base,
        // Every details field is optional, so an unnamed scanner starts from a name that already reads sensibly.
        name: defaultScannerName(teamName, 'monitor'),
        description: '',
        scanner_type: 'monitor',
        scanner_config: { prompt: '' },
    }
}

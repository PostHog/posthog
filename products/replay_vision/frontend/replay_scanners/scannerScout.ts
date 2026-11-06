import type {
    ScannerScoutCreateApi,
    ScannerTypeEnumApi,
    ScoutTemplateKeyEnumApi,
} from 'products/replay_vision/frontend/generated/api.schemas'
import type {
    SignalScoutConfigApi,
    SignalScoutOutputDestinationsApi,
} from 'products/signals/frontend/generated/api.schemas'
import { SIGNALS_SCOUT_SKILL_PREFIX } from 'products/signals/frontend/inbox/utils/scoutRunsWindow'

// pinned: what a scout's config records as its owner, alongside the scanner id in `source_id`.
// Signals stores the pair; the backend has the same constant in `scout_source.py`, and the two must
// agree or a scanner stops finding its own scouts.
const SCOUT_SOURCE_PRODUCT = 'replay_vision'

// pinned: the tag the backend's `VARIANT_ANALYSIS_TAG` puts on a variant analysis scout's config. The
// two must agree, or the template card offers a second scout the API then refuses.
const VARIANT_ANALYSIS_TAG = 'replay-vision-variant-analysis'

/** The scanner's variant analysis scout, if it has one. The API allows one per scanner. */
export function variantAnalysisScout(configs: SignalScoutConfigApi[]): SignalScoutConfigApi | undefined {
    return configs.find((config) => config.tags?.includes(VARIANT_ANALYSIS_TAG))
}

/** Whether this scout was stood up for this scanner. The pair is recorded on the config when the
 * scout is created and is not user-editable, so it cannot be lost the way a label could. */
export function isScannerScoutConfig(config: SignalScoutConfigApi, scannerId: string): boolean {
    return config.source_product === SCOUT_SOURCE_PRODUCT && config.source_id?.toLowerCase() === scannerId.toLowerCase()
}

/** What the name field accepts, and the only bound on it: the typed name is recorded as the scout
 * config's `display_name` and nothing else is derived from it. Kept in sync with the `display_name`
 * maxLength on the Signals scout config API. */
export const SCOUT_DISPLAY_NAME_MAX_LENGTH = 200

const SKILL_NAME_MAX_LENGTH = 64
// Room for the `-2`..`-99` a collision appends.
const COLLISION_SUFFIX_LENGTH = 3

function slugify(value: string): string {
    return value
        .toLowerCase()
        .replace(/[\s_]+/g, '-')
        .replace(/[^a-z0-9-]+/g, '')
        .replace(/-{2,}/g, '-')
        .replace(/^-|-$/g, '')
}

/** The scout's skill name, which is its id: fixed at creation, unique per team, and what the
 * runtime loads the scout's prompt by. Derived from the scanner and the template the person picked,
 * never from the name they typed, so nothing has to bound that name and the form can take one of
 * any length. Suffixes while taken.
 *
 * The scanner is in the slug because skill names are unique per team, not per scanner. Without it
 * the second scanner's daily digest becomes `signals-scout-daily-digest-2`, which reads as a second
 * digest on that scanner rather than the first, and the numbering climbs with every scanner a team
 * sets up. Template keys are already valid slugs and short, so only the scanner gives way to the
 * cap, and shortening it shortens the id alone, never a name anyone reads. */
export function scoutSkillName(
    scannerName: string,
    templateKey: ScannerScoutTemplateKey,
    takenNames: string[]
): string {
    const budget = SKILL_NAME_MAX_LENGTH - SIGNALS_SCOUT_SKILL_PREFIX.length - COLLISION_SUFFIX_LENGTH
    // Reserve the join dash and the whole template key, so only the scanner slug is trimmed.
    const scannerSlug = slugify(scannerName)
        .slice(0, Math.max(0, budget - templateKey.length - 1))
        .replace(/-$/, '')
    // Re-clamp the joined part to the same budget, so the cap holds even if the reservation above is
    // wrong for some future template key.
    const suffix = [scannerSlug, templateKey].filter(Boolean).join('-').slice(0, budget).replace(/-$/, '')
    const base = SIGNALS_SCOUT_SKILL_PREFIX + suffix
    const taken = new Set(takenNames)
    if (!taken.has(base)) {
        return base
    }
    for (let n = 2; ; n++) {
        const candidate = `${base}-${n}`
        if (!taken.has(candidate)) {
            return candidate
        }
    }
}

export type ScannerScoutTemplateKey = ScoutTemplateKeyEnumApi

/** Whether a scanner type is offered the root cause template, which needs outcomes to explain. */
export function hasRootCauseTemplate(scannerType: ScannerTypeEnumApi | undefined): boolean {
    // Mirrors the backend's template sets: only scanner types that sort sessions into outcomes have one.
    return scannerType === 'monitor' || scannerType === 'classifier' || scannerType === 'scorer'
}

/** Fewest sessions in a bucket before a root cause scout can name a cause. Below this the template
 * tells the scout to report `No clear cause`, so offering one would set up a scout that can't deliver. */
export const ROOT_CAUSE_MIN_SESSIONS = 20

/** Whether a scout was created from the given template. The skill name ends in the template key,
 * plus a `-<n>` suffix when the name was taken, and is fixed at creation. */
export function isTemplateScout(skillName: string, templateKey: ScannerScoutTemplateKey): boolean {
    return new RegExp(`-${templateKey}(-\\d+)?$`).test(skillName)
}

/** ALL-CAPS inside angle brackets marks what the author has to write; lowercase ones
 * (`<scanner name>`) are for the scout to fill at run time. */
export const SCOUT_PLACEHOLDER_PATTERN = /<[A-Z][^<>]*>/g

/** The unfilled slots in a scout's instructions. */
export function scoutBodyPlaceholders(body: string): string[] {
    return [...new Set(body.match(SCOUT_PLACEHOLDER_PATTERN) ?? [])]
}

/** The create-request body for a scanner's scout. `name`, `body`, and `cron` come from the review
 * form, seeded by the chosen template. */
export function scannerScoutCreatePayload(
    scannerName: string,
    overrides: {
        name: string
        body: string
        cron: string
        outputDestinations?: SignalScoutOutputDestinationsApi
        templateKey?: ScannerScoutTemplateKey
    }
): ScannerScoutCreateApi {
    return {
        // Asks the server to attach the record schema the variants view reads.
        ...(overrides.templateKey === 'variant-analysis' ? { variant_analysis: true } : {}),
        // Lets the server keep a body left exactly as the template rendered it on the template's latest text.
        ...(overrides.templateKey ? { template_key: overrides.templateKey } : {}),
        name: overrides.name,
        description:
            `Replay Vision scout for the scanner "${scannerName}". Reads the scanner's new observations on a schedule and files an inbox report when something is worth reporting.`.slice(
                0,
                4096
            ),
        body: overrides.body,
        config: {
            enabled: true,
            emit: true,
            run_cron_schedule: overrides.cron,
            // The scout files exactly one report per run, so the platform's own delivery posts that
            // digest to Slack once per run.
            output_destinations: overrides.outputDestinations ?? {},
        },
    }
}

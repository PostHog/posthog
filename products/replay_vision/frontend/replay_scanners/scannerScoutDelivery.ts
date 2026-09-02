import type { hogFunctionsCreate } from 'products/cdp/frontend/generated/api'

/** The create body's type, which the generated client doesn't export by name. */
type HogFunctionWriteBody = NonNullable<Parameters<typeof hogFunctionsCreate>[1]>

// pinned: the event the scout platform captures when a scout files a report. Exactly one fires per
// run, which is what makes it a safe delivery trigger. Slack needs no equivalent here: the
// platform's own delivery posts the same report.
export const SCOUT_REPORT_EMITTED_EVENT = '$scout_report_emitted'

// The edit event deliberately stays off the trigger. It carries only the fields an edit touched, so
// a note-only edit would deliver a blank title and summary, and a run may edit its report more than
// once, which would deliver that run twice.

// Only a surfaced report reached the inbox. A gate-skipped or suppressed one still captures the
// event, and delivering it would push content the platform decided not to show.
const SURFACED_OUTCOME = 'surfaced'

// The name a provisioned destination carries in Data pipelines, so a person can tell where it came
// from. Ownership is recorded on the scout's config, not inferred from this.
export const SCOUT_DESTINATION_NAME_PREFIX = 'Replay Vision · '

export const WEBHOOK_TEMPLATE_ID = 'template-webhook'

// Marks our payloads so a consumer can pin the schema and we can evolve it without breaking them.
// Mirrors the convention the vision-action webhooks used.
const WEBHOOK_HEADERS = { 'Content-Type': 'application/json', 'X-PostHog-Webhook-Version': '1' }

/** Whether a destination is one this scout's delivery provisioned: our template, our name, and this
 * scout's trigger. The id alone is not proof — a caller can point a config at any destination in the
 * project — and acting on it would let them use a teammate's permissions to overwrite or delete it. */
export function isScoutDestination(
    destination: { filters?: unknown; template?: unknown; name?: string | null },
    skillName: string
): boolean {
    const template = destination.template as { id?: string } | null | undefined
    const filters = destination.filters as
        | { events?: { id?: string }[]; properties?: { key?: string; value?: unknown }[] }
        | null
        | undefined
    return (
        template?.id === WEBHOOK_TEMPLATE_ID &&
        Boolean(destination.name?.startsWith(SCOUT_DESTINATION_NAME_PREFIX)) &&
        Boolean(filters?.events?.some((event) => event.id === SCOUT_REPORT_EMITTED_EVENT)) &&
        Boolean(filters?.properties?.some((property) => property.key === 'skill_name' && property.value === skillName))
    )
}

/** Why a webhook URL isn't usable, or null when it is. HTTPS only, since the payload carries
 * recording-derived findings, and no embedded credentials. */
export function webhookUrlError(url: string): string | null {
    let parsed: URL
    try {
        parsed = new URL(url)
    } catch {
        return 'Enter a valid URL'
    }
    if (parsed.protocol !== 'https:') {
        return 'The URL must start with https://'
    }
    if (parsed.username || parsed.password) {
        return 'The URL must not embed credentials'
    }
    return null
}

/** POSTs each digest a scout files to a URL, once per run. */
export function scoutWebhookDestinationPayload(
    skillName: string,
    scoutLabel: string,
    url: string
): HogFunctionWriteBody {
    const inputs = {
        url: { value: url },
        method: { value: 'POST' },
        headers: { value: WEBHOOK_HEADERS },
        body: {
            value: {
                source: 'replay_vision_scout',
                scout: '{event.properties.skill_name}',
                run_id: '{event.properties.run_id}',
                filed_at: '{event.timestamp}',
                digest: {
                    report_id: '{event.properties.report_id}',
                    title: '{event.properties.title}',
                    summary: '{event.properties.summary}',
                    priority: '{event.properties.priority}',
                    url: '{event.properties.report_url}',
                },
            },
        },
    }
    return {
        type: 'destination',
        enabled: true,
        template_id: WEBHOOK_TEMPLATE_ID,
        name: `${SCOUT_DESTINATION_NAME_PREFIX}${scoutLabel}`,
        description: `Sends each digest the "${scoutLabel}" Replay Vision scout files to a webhook.`,
        filters: {
            events: [{ id: SCOUT_REPORT_EMITTED_EVENT, type: 'events' }],
            properties: [
                { key: 'skill_name', value: skillName, operator: 'exact', type: 'event' },
                { key: 'outcome', value: SURFACED_OUTCOME, operator: 'exact', type: 'event' },
            ],
        },
        // The generated input type carries server-set fields (bytecode, order, transpiled) as
        // required, so a write-shaped literal can only reach it through `unknown`.
        inputs: inputs as unknown as HogFunctionWriteBody['inputs'],
    }
}

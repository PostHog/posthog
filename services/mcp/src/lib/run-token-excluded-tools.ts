// Tools a server-minted run token (one carrying `internal_run:read`) never gets. Such a run acts
// with nobody watching:
// - the run-start tools would let one run start more runs;
// - the posthog-support tools reach PostHog staff verified as the user. The backend refuses run
//   tokens there too; dropping the tools keeps them out of the run's tool list.
export const RUN_TOKEN_EXCLUDED_TOOLS: readonly string[] = [
    'tasks-run-create',
    'tasks-create-and-run',
    'posthog-support-ticket-create',
    'posthog-support-tickets-list',
    'posthog-support-ticket-get',
    'posthog-support-ticket-reply',
]

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const DEMO_ID = /^demo-[a-z0-9-]+$/

/** Checks a report id from a route before it reaches an API path. Demo fixture ids count only in demo mode. */
export function isReportId(value: string, demo: boolean): boolean {
    return UUID.test(value) || (demo && DEMO_ID.test(value))
}

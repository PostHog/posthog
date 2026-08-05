/**
 * Gates the whole Support surface: the sidebar item and the /code/support
 * routes (attention queue + ticket detail). Internal-first dogfood; mirrors
 * the `future-support` flag on the PostHog side. Deliberately distinct from
 * the server-side `product-support-*` flag family, which gates the
 * Conversations ticket product itself, not this harness.
 */
export const FUTURE_SUPPORT_FLAG = "future-support";

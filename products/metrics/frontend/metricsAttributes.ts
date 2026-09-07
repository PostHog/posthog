// Attribute keys shared by the viewer's filter bar and the cross-product link builders. A leaf
// module on purpose: metricsLinks and metricsViewerLogic both need these, and importing one from
// the other would put a kea logic in an import cycle.

/** Ingestion promotes `service.name` to its own column, so this is the one label queries can narrow by cheaply. */
export const SERVICE_NAME_KEY = 'service_name'

/**
 * The anchored regex standing in for senders that set no service name: the empty string cannot
 * survive the filter pipeline, which drops empty chip values.
 */
export const EMPTY_SERVICE_PATTERN = '^$'

/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface ChartImageApi {
    /** Base64-encoded PNG image bytes to publish. Must decode to a PNG no larger than 5 MiB. */
    image_base64: string
    /** Optional title used to build a readable filename for the published image. */
    title?: string
    /**
     * Optional short id of the insight this image visualizes, recorded for provenance.
     * @nullable
     */
    insight_short_id?: string | null
    /** Id of the published image asset. */
    readonly id: number
    /** Durable signed URL of the published PNG, fetchable without authentication so it can be posted to Slack. */
    readonly image_url: string
}

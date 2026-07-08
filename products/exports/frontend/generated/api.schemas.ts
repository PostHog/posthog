/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `image/png` - image/png
 * `application/pdf` - application/pdf
 * `text/csv` - text/csv
 * `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` - application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
 * `video/webm` - video/webm
 * `video/mp4` - video/mp4
 * `image/gif` - image/gif
 * `application/json` - application/json
 */
export type ExportFormatEnumApi = (typeof ExportFormatEnumApi)[keyof typeof ExportFormatEnumApi]

export const ExportFormatEnumApi = {
    ImagePng: 'image/png',
    ApplicationPdf: 'application/pdf',
    TextCsv: 'text/csv',
    ApplicationVndopenxmlformatsOfficedocumentspreadsheetmlsheet:
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    VideoWebm: 'video/webm',
    VideoMp4: 'video/mp4',
    ImageGif: 'image/gif',
    ApplicationJson: 'application/json',
} as const

/**
 * Standard ExportedAsset serializer that doesn't return content.
 */
export interface ExportedAssetApi {
    readonly id: number
    /** @nullable */
    dashboard?: number | null
    /** @nullable */
    insight?: number | null
    export_format: ExportFormatEnumApi
    readonly created_at: string
    readonly has_content: boolean
    export_context?: unknown
    readonly filename: string
    /** @nullable */
    readonly expires_after: string | null
    /** @nullable */
    readonly exception: string | null
}

export interface PaginatedExportedAssetListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ExportedAssetApi[]
}

export type ExportsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

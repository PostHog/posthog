import { ExternalDataSource } from '~/types'

export function revenueViewName(source: Pick<ExternalDataSource, 'source_type' | 'prefix'>, suffix: string): string {
    const sourceType = source.source_type.toLowerCase()
    const prefix = source.prefix?.replace(/^_+|_+$/g, '')
    return prefix ? `${sourceType}.${prefix}.${suffix}` : `${sourceType}.${suffix}`
}

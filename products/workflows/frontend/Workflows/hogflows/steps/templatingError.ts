import { LiquidRenderer } from 'lib/utils/liquid'

export function getTemplatingError(value: string, templating?: string): string | undefined {
    if (templating === 'liquid' && typeof value === 'string') {
        try {
            LiquidRenderer.parse(value)
        } catch (e: any) {
            return `Liquid template error: ${e.message}`
        }
    }
}

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Mindmap',
    urls: {
        mindmap: (): string => '/mindmap',
    },
}

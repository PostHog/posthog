export async function rasterizeLogo(svg: string): Promise<File> {
    const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }))
    try {
        const image = new Image()
        await new Promise<void>((resolve, reject) => {
            image.onload = () => resolve()
            image.onerror = () => reject(new Error('Could not read this SVG. Upload a PNG instead.'))
            image.src = url
        })
        if (!image.naturalWidth || !image.naturalHeight) {
            throw new Error('This SVG has no image dimensions. Upload a PNG instead.')
        }
        const scale = Math.min(320 / image.naturalWidth, 320 / image.naturalHeight)
        const canvas = document.createElement('canvas')
        canvas.width = Math.max(1, Math.round(image.naturalWidth * scale))
        canvas.height = Math.max(1, Math.round(image.naturalHeight * scale))
        const context = canvas.getContext('2d')
        if (!context) {
            throw new Error('Could not convert this SVG. Upload a PNG instead.')
        }
        context.drawImage(image, 0, 0, canvas.width, canvas.height)
        const png = await new Promise<Blob>((resolve, reject) =>
            canvas.toBlob(
                (blob) =>
                    blob ? resolve(blob) : reject(new Error('Could not convert this SVG. Upload a PNG instead.')),
                'image/png'
            )
        )
        return new File([png], 'email-brand-logo.png', { type: 'image/png' })
    } finally {
        URL.revokeObjectURL(url)
    }
}

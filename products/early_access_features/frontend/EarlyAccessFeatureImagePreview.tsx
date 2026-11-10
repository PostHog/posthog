export interface EarlyAccessFeatureImagePreviewProps {
    imageUrl?: string
}

export function EarlyAccessFeatureImagePreview({ imageUrl }: EarlyAccessFeatureImagePreviewProps): JSX.Element {
    return (
        <div>
            <b>Image</b>
            <div>
                {imageUrl ? (
                    <img
                        src={imageUrl}
                        alt="Preview of the feature"
                        className="block max-h-60 max-w-full rounded border object-contain"
                    />
                ) : (
                    <span className="text-secondary">No image</span>
                )}
            </div>
        </div>
    )
}

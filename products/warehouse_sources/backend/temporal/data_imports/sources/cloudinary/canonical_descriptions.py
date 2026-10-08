from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_ASSET_COLUMNS = {
    "asset_id": "Unique identifier for the asset, stable across renames.",
    "public_id": "Identifier used to build the asset's delivery URL, including its folder path.",
    "folder": "Folder the asset sits in.",
    "format": "File format, such as jpg, png, or mp4.",
    "version": "Version number, which changes each time the asset is overwritten.",
    "resource_type": "Asset type: image, video, or raw.",
    "type": "Delivery type, such as upload, private, or authenticated.",
    "created_at": "Date and time the asset was uploaded.",
    "uploaded_at": "Date and time the current version was uploaded.",
    "bytes": "File size in bytes.",
    "width": "Width in pixels.",
    "height": "Height in pixels.",
    "url": "HTTP delivery URL for the asset.",
    "secure_url": "HTTPS delivery URL for the asset.",
    "tags": "Tags applied to the asset.",
    "context": "Contextual metadata key-value pairs stored on the asset.",
    "access_mode": "Whether the asset is publicly accessible or restricted.",
    "backup_bytes": "Size of the asset's backed-up versions in bytes.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "images": {
        "description": "An image in the Cloudinary media library, with its delivery URLs, size, and metadata.",
        "docs_url": "https://cloudinary.com/documentation/admin_api#get_resources",
        "columns": dict(_ASSET_COLUMNS),
    },
    "videos": {
        "description": "A video in the Cloudinary media library, with its delivery URLs, size, and metadata.",
        "docs_url": "https://cloudinary.com/documentation/admin_api#get_resources",
        "columns": {**_ASSET_COLUMNS, "duration": "Length of the video in seconds."},
    },
    "raw_files": {
        "description": "A raw file in the Cloudinary media library, meaning one stored without image or video processing.",
        "docs_url": "https://cloudinary.com/documentation/admin_api#get_resources",
        "columns": dict(_ASSET_COLUMNS),
    },
    "folders": {
        "description": "A folder in the Cloudinary media library.",
        "docs_url": "https://cloudinary.com/documentation/admin_api#get_folders",
        "columns": {
            "name": "Folder name.",
            "path": "Full path of the folder, including its parents.",
            "external_id": "Cloudinary's identifier for the folder.",
        },
    },
    "transformations": {
        "description": "A stored transformation, meaning a named recipe Cloudinary applies when delivering an asset.",
        "docs_url": "https://cloudinary.com/documentation/admin_api#get_transformations",
        "columns": {
            "name": "Transformation name, either the named transformation or its parameter string.",
            "named": "Whether the transformation was given a name rather than generated from parameters.",
            "allowed_for_strict": "Whether the transformation is allowed when strict transformations are on.",
            "used": "Whether the transformation has been used to deliver an asset.",
        },
    },
    "upload_presets": {
        "description": "An upload preset, meaning a saved set of upload options that clients can apply by name.",
        "docs_url": "https://cloudinary.com/documentation/admin_api#get_upload_presets",
        "columns": {
            "name": "Preset name, used by clients when uploading.",
            "unsigned": "Whether the preset allows unsigned uploads from the browser.",
            "settings": "Upload options the preset applies, such as folder, tags, and transformations.",
        },
    },
}

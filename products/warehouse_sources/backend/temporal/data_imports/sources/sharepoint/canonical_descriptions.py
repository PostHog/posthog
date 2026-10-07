"""Canonical, documentation-sourced descriptions for SharePoint endpoints and columns.

Sourced from the Microsoft Graph v1.0 SharePoint and files reference
(https://learn.microsoft.com/en-us/graph/api/resources/sharepoint). Keyed by the endpoint names in
`settings.py` `SHAREPOINT_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced table.
Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "sites": {
        "description": "A SharePoint site: a container for lists, document libraries, and pages.",
        "docs_url": "https://learn.microsoft.com/en-us/graph/api/resources/site",
        "columns": {
            "id": "Unique identifier of the site, in the form hostname,site-collection-id,web-id.",
            "name": "Name of the site.",
            "displayName": "Full title of the site.",
            "description": "Description of the site.",
            "webUrl": "URL that opens the site in a browser.",
            "createdDateTime": "Date and time the site was created.",
            "lastModifiedDateTime": "Date and time the site was last modified.",
            "isPersonalSite": "Whether the site is a personal OneDrive site.",
            "siteCollection": "Details of the site collection the site belongs to, such as its hostname.",
            "root": "Present when the site is the root site of its site collection.",
        },
    },
    "lists": {
        "description": "A list or document library in a SharePoint site.",
        "docs_url": "https://learn.microsoft.com/en-us/graph/api/resources/list",
        "columns": {
            "site_id": "Identifier of the site the list belongs to.",
            "id": "Unique identifier of the list.",
            "name": "Internal name of the list.",
            "displayName": "Display title of the list.",
            "description": "Description of the list.",
            "webUrl": "URL that opens the list in a browser.",
            "createdDateTime": "Date and time the list was created.",
            "lastModifiedDateTime": "Date and time the list was last modified.",
            "createdBy": "Identity of the user or app that created the list.",
            "lastModifiedBy": "Identity of the user or app that last modified the list.",
            "list": "List details: the template it was created from, whether it is hidden, and whether content types are enabled.",
            "eTag": "Version tag of the list.",
        },
    },
    "list_items": {
        "description": "An item in a SharePoint list, such as a row in a custom list or a file entry in a document library.",
        "docs_url": "https://learn.microsoft.com/en-us/graph/api/resources/listitem",
        "columns": {
            "site_id": "Identifier of the site the item's list belongs to.",
            "list_id": "Identifier of the list the item belongs to.",
            "id": "Identifier of the item, unique within its list.",
            "fields": "Values of the list's columns for this item, keyed by column internal name.",
            "webUrl": "URL that opens the item in a browser.",
            "createdDateTime": "Date and time the item was created.",
            "lastModifiedDateTime": "Date and time the item was last modified.",
            "createdBy": "Identity of the user or app that created the item.",
            "lastModifiedBy": "Identity of the user or app that last modified the item.",
            "contentType": "Content type of the item.",
            "parentReference": "Reference to the list that contains the item.",
            "eTag": "Version tag of the item.",
        },
    },
    "drives": {
        "description": "A document library in a SharePoint site, exposed as a drive.",
        "docs_url": "https://learn.microsoft.com/en-us/graph/api/resources/drive",
        "columns": {
            "site_id": "Identifier of the site the drive belongs to.",
            "id": "Unique identifier of the drive.",
            "name": "Name of the drive.",
            "description": "Description of the drive.",
            "driveType": "Type of drive. SharePoint document libraries are documentLibrary.",
            "webUrl": "URL that opens the document library in a browser.",
            "createdDateTime": "Date and time the drive was created.",
            "lastModifiedDateTime": "Date and time the drive was last modified.",
            "createdBy": "Identity of the user or app that created the drive.",
            "lastModifiedBy": "Identity of the user or app that last modified the drive.",
            "owner": "Identity of the owner of the drive.",
            "quota": "Storage quota of the drive.",
        },
    },
    "drive_items": {
        "description": "A file or folder in a SharePoint document library. Rows hold metadata only, not file contents.",
        "docs_url": "https://learn.microsoft.com/en-us/graph/api/resources/driveitem",
        "columns": {
            "site_id": "Identifier of the site the drive belongs to.",
            "drive_id": "Identifier of the drive (document library) the item belongs to.",
            "id": "Identifier of the item, unique within its drive.",
            "name": "File or folder name.",
            "size": "Size of the item in bytes.",
            "webUrl": "URL that opens the item in a browser.",
            "createdDateTime": "Date and time the item was created.",
            "lastModifiedDateTime": "Date and time the item was last modified.",
            "createdBy": "Identity of the user or app that created the item.",
            "lastModifiedBy": "Identity of the user or app that last modified the item.",
            "file": "File details, such as MIME type and hashes. Absent for folders.",
            "folder": "Folder details, such as the child count. Absent for files.",
            "parentReference": "Reference to the parent folder and drive of the item.",
            "fileSystemInfo": "Created and modified times as reported by the client that uploaded the file.",
            "eTag": "Version tag of the whole item, including metadata.",
            "cTag": "Version tag of the item's content.",
            "root": "Present when the item is the root folder of the drive.",
        },
    },
}

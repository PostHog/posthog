# File Marketing Source Adapter

from .self_managed import SelfManagedAdapter


class FileSourceAdapter(SelfManagedAdapter):
    """
    Adapter for managed sources that import spend data from files: Amazon S3, Google Cloud Storage,
    Azure Blob Storage, Cloudflare R2 and file uploads.

    These sources replace self-managed tables. They need the same column mapping, so the adapter
    shares all field resolution and query-building logic with SelfManagedAdapter.
    """

    def get_source_type(self) -> str:
        return self.config.source_type

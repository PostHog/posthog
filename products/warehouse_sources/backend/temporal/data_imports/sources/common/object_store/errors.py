# Error message prefixes. `get_non_retryable_errors` matches on these, so they have to stay stable
# and stay out of the interpolated part of each message.
INVALID_CONFIG_ERROR = "The storage settings are invalid"
BLOCKED_LOCATION_ERROR = "PostHog can't import from this storage location"
ACCESS_DENIED_ERROR = "The storage provider denied access to the bucket"
NO_SUCH_BUCKET_ERROR = "The bucket doesn't exist"
WRONG_REGION_ERROR = "The bucket is in a different region"
NO_IMPORTABLE_FILES_ERROR = "No importable files were found"
NO_TABLE_FILES_ERROR = "No files are available for table"
TOO_MANY_FILES_ERROR = "The table has more files than PostHog can import"
FILE_PARSE_ERROR = "Couldn't parse the file"
DELTA_UNSUPPORTED_ERROR = "The Delta table uses features PostHog can't read"
DELTA_READ_ERROR = "Couldn't read the Delta table"

# S3 error codes, and the message S3 sends with a 301, that mean the request went to the wrong
# regional endpoint for this bucket. s3fs keeps only the message when it translates the error.
_WRONG_REGION_MARKERS = (
    "PermanentRedirect",
    "AuthorizationHeaderMalformed",
    "IllegalLocationConstraint",
    "must be addressed using the specified endpoint",
)


class ObjectStorageError(Exception):
    """A problem the user has to fix: rejected credentials, a missing bucket, an unreadable file."""


def translate_storage_error(error: Exception, location: str) -> Exception:
    """Map a filesystem error to an `ObjectStorageError` with a stable prefix, or return it unchanged.

    s3fs turns S3 error codes into builtin exceptions: `AccessDenied`, `InvalidAccessKeyId` and
    `SignatureDoesNotMatch` become `PermissionError`, and `NoSuchBucket` becomes `FileNotFoundError`.
    Anything else stays as it is, so a transient failure keeps its retryable message.
    """
    if isinstance(error, ObjectStorageError):
        return error
    if isinstance(error, PermissionError):
        return ObjectStorageError(
            f"{ACCESS_DENIED_ERROR} '{location}'. Check the access key and secret, and that the key can list "
            "and read objects in this bucket."
        )
    if isinstance(error, FileNotFoundError):
        return ObjectStorageError(f"{NO_SUCH_BUCKET_ERROR}: '{location}'. Check the bucket name.")
    message = str(error)
    if any(marker in message for marker in _WRONG_REGION_MARKERS):
        return ObjectStorageError(f"{WRONG_REGION_ERROR} from the one configured for '{location}'. Fix the region.")
    return error

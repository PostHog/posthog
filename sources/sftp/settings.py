DEFAULT_PORT = 22
CONNECT_TIMEOUT_SECONDS = 30
# Per-operation read timeout for directory and file transfers. A responsive server keeps data
# flowing well within this, so it only trips on a stalled server holding an iterator thread.
READ_TIMEOUT_SECONDS = 300

# Paramiko builds one prefetch descriptor per 32 KiB block up to the requested size, so a server that
# reports an enormous file size could balloon that list. Cap it: bytes past this are read on demand.
MAX_PREFETCH_BYTES = 256 * 1024 * 1024

# A remote tree is walked breadth-first with all three bounds enforced: an SFTP server can expose an
# arbitrarily deep/wide tree, and discovery has to terminate without the user configuring limits.
MAX_DIRECTORY_DEPTH = 5
MAX_FILES = 1000
# Depth and file count alone don't bound the walk: `MAX_FILES` counts only files matching the
# pattern, so a pattern matching nothing (or a tree of nothing but folders) leaves the breadth of
# each level unbounded. Capping how many folders are ever queued bounds both the listing round trips
# and the queue itself.
MAX_DIRECTORIES = 1000

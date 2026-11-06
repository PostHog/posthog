"""
Facade re-export for notebook kernel sandbox usage events.

The kernel status endpoint can be the first code path that notices a sandbox has ended, so it
records that end. Presentation may only reach in-product code through this package, so the
recorder stays in `kernel_sandbox_usage` and is re-exported here.
"""

from ..kernel_sandbox_usage import record_sandbox_ended_by_id as record_sandbox_ended_by_id

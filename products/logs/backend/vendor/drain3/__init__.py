# Vendored from drain3 0.9.11 (https://github.com/IBM/Drain3). Only the in-memory mining algorithm
# is taken: drain.py + masking.py (MIT) and simple_profiler.py (Apache-2.0); each file carries its
# full upstream attribution + license header. drain3's TemplateMiner persistence wrapper is
# intentionally omitted — it is the sole importer of jsonpickle (an insecure-by-design
# deserializer), and we mine at query time in memory, so Drain state is never persisted/loaded.
# Re-vendor: `pip download drain3==<v> --no-deps --no-binary :all:`, copy the three files, then
# re-apply the relative import + repo-style fixups (ruff format/fix, ty annotations).
from .drain import Drain
from .masking import LogMasker, MaskingInstruction

__all__ = ["Drain", "LogMasker", "MaskingInstruction"]

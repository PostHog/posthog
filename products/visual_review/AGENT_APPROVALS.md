---
stamphog:
  size_gate:
    max_files: 50
---

Visual review PRs are often mechanical and wide: snapshot churn, per-story updates, and bulk screenshot regeneration routinely touch many files at once.
Breadth alone is not a red flag here, so a larger file count may be reviewed more leniently than the global default.

Correctness concerns get the usual full scrutiny: authentication, data handling, and CI or workflow changes are judged exactly as they are anywhere else.
This guidance only relaxes the file-count ceiling; it never lowers the bar for the deny rules or the refusal criteria.

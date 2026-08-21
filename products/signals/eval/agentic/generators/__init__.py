"""Programmatic generation of large, grounded eval datasets.

Hand-authoring hundreds of cases is impractical and low-quality. These generators produce
100+ cases per step from the committed synthetic project manifest, public OSS registry, and
source/verdict templates. Output is written to committed JSON under ``cases/generated/`` so
the suite is inspectable, diffable, safe to publish, and runnable without a database — regenerate
with ``python manage.py generate_eval_cases``.
"""

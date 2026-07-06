"""Programmatic generation of large, grounded eval datasets.

Hand-authoring hundreds of cases is impractical and low-quality. These generators produce
100+ cases per step, grounded in the eval project's real data where possible (repo cache,
error-tracking issues, events, experiments) and templated for source/verdict variety. Output
is written to committed JSON under ``cases/generated/`` so the suite is inspectable, diffable,
and runnable without a database — regenerate with ``python manage.py generate_eval_cases``.
"""

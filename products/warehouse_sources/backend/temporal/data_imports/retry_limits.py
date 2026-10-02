# The largest retry cap an import activity gets. It lives apart from `external_data_job` so the
# schema model can read it: that module loads temporalio, and the model loads during django.setup().
MAX_RESUMABLE_SOURCE_RETRIES_PRODUCTION = 20

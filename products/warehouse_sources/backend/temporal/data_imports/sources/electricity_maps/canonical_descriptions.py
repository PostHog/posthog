"""Canonical, documentation-sourced descriptions for Electricity Maps endpoints and columns.

Sourced from the official Electricity Maps API reference (https://app.electricitymaps.com/docs/api).
Keyed by the endpoint names in `settings.py` `ENDPOINTS`, which match the `ExternalDataSchema.name`
of a synced Electricity Maps table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "carbon_intensity": {
        "description": "Hourly carbon intensity of electricity consumed in a zone, in grams of "
        "CO2 equivalent per kilowatt-hour (gCO2eq/kWh).",
        "docs_url": "https://app.electricitymaps.com/docs/api",
        "columns": {
            "zone": "Identifier of the electricity grid zone, e.g. `DE` or `DK-DK1`.",
            "carbonIntensity": "Carbon intensity of consumed electricity for this hour, in gCO2eq/kWh.",
            "datetime": "UTC start of the hour this measurement covers.",
            "updatedAt": "When Electricity Maps last updated this data point.",
            "createdAt": "When Electricity Maps first created this data point.",
            "emissionFactorType": "Type of emission factors used to compute the intensity: `lifecycle` or `direct`.",
            "isEstimated": "Whether this value is an estimate rather than measured data.",
            "estimationMethod": "Model used to produce the estimate, or null for measured data.",
        },
    },
    "power_breakdown": {
        # get_canonical_descriptions() isn't threaded with the resolved api_version pin, so these
        # hints apply to every pin. The v3 wire's breakdown fields (powerConsumptionBreakdown,
        # powerProductionTotal, fossilFreePercentage, createdAt, and similar) have no equivalent in
        # the v4 electricity-mix wire's "mix"/"flows" shape, so listing them here would mislabel a
        # v4-pinned sync's columns. Only the fields verified identical on both wires are curated;
        # the rest fall back to LLM enrichment.
        "description": "Hourly origin of electricity in a zone: generation by source, cross-border "
        "flows, and storage charge/discharge.",
        "docs_url": "https://app.electricitymaps.com/docs/api",
        "columns": {
            "zone": "Identifier of the electricity grid zone, e.g. `DE` or `DK-DK1`.",
            "datetime": "UTC start of the hour this measurement covers.",
            "updatedAt": "When Electricity Maps last updated this data point.",
            "isEstimated": "Whether this value is an estimate rather than measured data.",
            "estimationMethod": "Model used to produce the estimate, or null for measured data.",
        },
    },
}

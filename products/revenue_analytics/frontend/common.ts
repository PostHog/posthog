// Zero-dependency module for values that need to be shared without dragging in the full
// revenueAnalyticsLogic graph. revenueAnalyticsLogic imports scenes/max/maxTypes, and maxTypes needs
// RevenueAnalyticsQuery — importing it straight from the logic forms an import cycle. Keep shared,
// dependency-free primitives here instead.

export enum RevenueAnalyticsQuery {
    OVERVIEW,
    MRR,
    GROSS_REVENUE,
    METRICS,
    TOP_CUSTOMERS,
}

export const earlyAccessFeatures = (): string => '/early_access_features'
export const earlyAccessFeature =
    /** @param id A UUID or 'new'. ':id' for routing. */
    (id: string): string => `/early_access_features/${id}`

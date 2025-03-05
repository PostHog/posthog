export const urls = {
    earlyAccessFeatures: (): string => '/early_access_features',
    earlyAccessFeature:
        /** @param id A UUID or 'new'. ':id' for routing. */
        (id: string): string => `/early_access_features/${id}`,
}

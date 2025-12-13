import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { DEFAULT_CLUSTERING_PARAMS, clustersAdminLogic } from './clustersAdminLogic'

export function ClusteringAdminModal(): JSX.Element {
    const { isModalOpen, params, isRunning } = useValues(clustersAdminLogic)
    const { closeModal, setParams, triggerClusteringRun, resetParams } = useActions(clustersAdminLogic)

    return (
        <LemonModal
            isOpen={isModalOpen}
            onClose={closeModal}
            title="Run clustering workflow"
            description="Configure and trigger a clustering workflow with custom parameters for experimentation."
            footer={
                <>
                    <LemonButton type="secondary" onClick={resetParams} disabled={isRunning}>
                        Reset to defaults
                    </LemonButton>
                    <div className="flex-1" />
                    <LemonButton type="secondary" onClick={closeModal} disabled={isRunning}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={triggerClusteringRun} loading={isRunning}>
                        Run clustering
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-6">
                {/* Run Label */}
                <div>
                    <h4 className="font-semibold mb-3">Experiment tracking</h4>
                    <div>
                        <label className="text-sm font-medium mb-1 block">Run label</label>
                        <LemonInput
                            type="text"
                            value={params.run_label}
                            onChange={(value) => setParams({ run_label: value })}
                            placeholder="e.g., pca-100-l2-test"
                            fullWidth
                        />
                        <div className="text-xs text-muted mt-1">
                            Optional label added as suffix to run ID for tracking experiments
                        </div>
                    </div>
                </div>

                {/* Trace Filters */}
                <div>
                    <h4 className="font-semibold mb-3">Trace filters</h4>
                    <div className="text-sm text-muted mb-3">
                        Only cluster traces matching these criteria. Leave empty to include all traces with embeddings.
                    </div>
                    <PropertyFilters
                        propertyFilters={params.trace_filters}
                        onChange={(properties) => setParams({ trace_filters: properties })}
                        pageKey="clustering-trace-filters"
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.EventProperties,
                            TaxonomicFilterGroupType.EventMetadata,
                        ]}
                        addText="Add trace filter"
                        hasRowOperator={false}
                        sendAllKeyUpdates
                        allowRelativeDateOptions={false}
                    />
                    <div className="text-xs text-muted mt-2">
                        <strong>Examples:</strong> $ai_model = "gpt-4", $ai_provider = "openai", $ai_total_cost_usd &gt;
                        0.01
                    </div>
                </div>

                {/* Basic Parameters */}
                <div>
                    <h4 className="font-semibold mb-3">Basic parameters</h4>
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="text-sm font-medium mb-1 block">Lookback days</label>
                            <LemonInput
                                type="number"
                                min={1}
                                max={90}
                                value={params.lookback_days}
                                onChange={(value) => setParams({ lookback_days: Number(value) })}
                                fullWidth
                            />
                            <div className="text-xs text-muted mt-1">
                                Days of traces to analyze (default: {DEFAULT_CLUSTERING_PARAMS.lookback_days})
                            </div>
                        </div>
                        <div>
                            <label className="text-sm font-medium mb-1 block">Max samples</label>
                            <LemonInput
                                type="number"
                                min={20}
                                max={10000}
                                value={params.max_samples}
                                onChange={(value) => setParams({ max_samples: Number(value) })}
                                fullWidth
                            />
                            <div className="text-xs text-muted mt-1">
                                Maximum traces to cluster (default: {DEFAULT_CLUSTERING_PARAMS.max_samples})
                            </div>
                        </div>
                    </div>
                </div>

                {/* Embedding Preprocessing */}
                <div>
                    <h4 className="font-semibold mb-3">Embedding preprocessing</h4>
                    <div>
                        <label className="text-sm font-medium mb-1 block">Normalization</label>
                        <LemonSelect
                            value={params.embedding_normalization}
                            onChange={(value) => setParams({ embedding_normalization: value })}
                            options={[
                                { value: 'none', label: 'None (raw embeddings)' },
                                { value: 'l2', label: 'L2 normalize' },
                            ]}
                            fullWidth
                        />
                        <div className="text-xs text-muted mt-1">
                            L2 normalization can help with embeddings of varying magnitudes
                        </div>
                    </div>
                </div>

                {/* Dimensionality Reduction */}
                <div>
                    <h4 className="font-semibold mb-3">Dimensionality reduction</h4>
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="text-sm font-medium mb-1 block">Method</label>
                            <LemonSelect
                                value={params.dimensionality_reduction_method}
                                onChange={(value) => setParams({ dimensionality_reduction_method: value })}
                                options={[
                                    { value: 'none', label: 'None (raw 3072 dims)' },
                                    { value: 'umap', label: 'UMAP' },
                                    { value: 'pca', label: 'PCA' },
                                ]}
                                fullWidth
                            />
                            <div className="text-xs text-muted mt-1">UMAP is slower but better for clustering</div>
                        </div>
                        <div>
                            <label className="text-sm font-medium mb-1 block">Target dimensions</label>
                            <LemonInput
                                type="number"
                                min={2}
                                max={500}
                                value={params.dimensionality_reduction_ndims}
                                onChange={(value) => setParams({ dimensionality_reduction_ndims: Number(value) })}
                                fullWidth
                                disabled={params.dimensionality_reduction_method === 'none'}
                            />
                            <div className="text-xs text-muted mt-1">
                                Number of dimensions (default:{' '}
                                {DEFAULT_CLUSTERING_PARAMS.dimensionality_reduction_ndims})
                            </div>
                        </div>
                    </div>
                </div>

                {/* Clustering Method */}
                <div>
                    <h4 className="font-semibold mb-3">Clustering algorithm</h4>
                    <div>
                        <label className="text-sm font-medium mb-1 block">Method</label>
                        <LemonSelect
                            value={params.clustering_method}
                            onChange={(value) => setParams({ clustering_method: value })}
                            options={[
                                { value: 'hdbscan', label: 'HDBSCAN (density-based, auto k)' },
                                { value: 'kmeans', label: 'K-means (centroid-based)' },
                            ]}
                            fullWidth
                        />
                        <div className="text-xs text-muted mt-1">
                            HDBSCAN auto-determines clusters and identifies outliers. K-means uses silhouette score to
                            pick optimal k.
                        </div>
                    </div>
                </div>

                {/* HDBSCAN Parameters */}
                {params.clustering_method === 'hdbscan' && (
                    <div>
                        <h4 className="font-semibold mb-3">HDBSCAN parameters</h4>
                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <label className="text-sm font-medium mb-1 block">min_cluster_size_fraction</label>
                                <LemonInput
                                    type="number"
                                    min={0.01}
                                    max={0.5}
                                    step={0.01}
                                    value={params.min_cluster_size_fraction}
                                    onChange={(value) => setParams({ min_cluster_size_fraction: Number(value) })}
                                    fullWidth
                                />
                                <div className="text-xs text-muted mt-1">
                                    Min cluster as % of samples (default:{' '}
                                    {(DEFAULT_CLUSTERING_PARAMS.min_cluster_size_fraction * 100).toFixed(0)}%)
                                </div>
                            </div>
                            <div>
                                <label className="text-sm font-medium mb-1 block">min_samples</label>
                                <LemonInput
                                    type="number"
                                    min={1}
                                    max={100}
                                    value={params.hdbscan_min_samples}
                                    onChange={(value) => setParams({ hdbscan_min_samples: Number(value) })}
                                    fullWidth
                                />
                                <div className="text-xs text-muted mt-1">
                                    Higher = more conservative (default: {DEFAULT_CLUSTERING_PARAMS.hdbscan_min_samples}
                                    )
                                </div>
                            </div>
                        </div>
                    </div>
                )}

                {/* K-means Parameters */}
                {params.clustering_method === 'kmeans' && (
                    <div>
                        <h4 className="font-semibold mb-3">K-means parameters</h4>
                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <label className="text-sm font-medium mb-1 block">Min k</label>
                                <LemonInput
                                    type="number"
                                    min={2}
                                    max={50}
                                    value={params.kmeans_min_k}
                                    onChange={(value) => setParams({ kmeans_min_k: Number(value) })}
                                    fullWidth
                                />
                                <div className="text-xs text-muted mt-1">
                                    Minimum clusters to try (default: {DEFAULT_CLUSTERING_PARAMS.kmeans_min_k})
                                </div>
                            </div>
                            <div>
                                <label className="text-sm font-medium mb-1 block">Max k</label>
                                <LemonInput
                                    type="number"
                                    min={2}
                                    max={100}
                                    value={params.kmeans_max_k}
                                    onChange={(value) => setParams({ kmeans_max_k: Number(value) })}
                                    fullWidth
                                />
                                <div className="text-xs text-muted mt-1">
                                    Maximum clusters to try (default: {DEFAULT_CLUSTERING_PARAMS.kmeans_max_k})
                                </div>
                            </div>
                        </div>
                    </div>
                )}

                {/* Visualization */}
                <div>
                    <h4 className="font-semibold mb-3">Visualization</h4>
                    <div>
                        <label className="text-sm font-medium mb-1 block">2D scatter plot method</label>
                        <LemonSelect
                            value={params.visualization_method}
                            onChange={(value) => setParams({ visualization_method: value })}
                            options={[
                                { value: 'umap', label: 'UMAP' },
                                { value: 'pca', label: 'PCA' },
                                { value: 'tsne', label: 't-SNE' },
                            ]}
                            fullWidth
                        />
                        <div className="text-xs text-muted mt-1">
                            Method for reducing cluster embeddings to 2D for the scatter plot visualization
                        </div>
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}

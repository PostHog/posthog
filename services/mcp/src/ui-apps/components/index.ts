// Main entry point - routes to the correct visualizer based on _visualization field
export { Component } from './Component'

// Smart visualizers - transform structured data for rendering
export { TrendsVisualizer } from './TrendsVisualizer'
export { FunnelVisualizer } from './FunnelVisualizer'
export { TableVisualizer } from './TableVisualizer'
export { PostHogLink } from './PostHogLink'

// Dumb chart components - receive pre-processed data
export * from './charts'

export * from './types'
export * from './utils'

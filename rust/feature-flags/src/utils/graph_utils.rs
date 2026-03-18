use std::collections::{HashMap, HashSet, VecDeque};

use petgraph::{
    algo::toposort,
    graph::{DiGraph, NodeIndex},
};

use crate::api::errors::FlagError;
use crate::flags::flag_models::FeatureFlag;
use crate::metrics::consts::{
    FLAG_DEPENDENCY_GRAPH_BUILD_COUNTER, FLAG_DEPENDENCY_GRAPH_BUILD_TIME,
    FLAG_DEPENDENCY_GRAPH_PATH_GRAPH, FLAG_DEPENDENCY_GRAPH_PATH_PRECOMPUTED,
    FLAG_EVALUATION_ERROR_COUNTER, FLAG_MISSING_REQUESTED_FLAG_KEY, TOMBSTONE_COUNTER,
};
use common_metrics::{inc, timing_guard};
use tracing::warn;

/// Logs a warning and increments the error counter when a requested flag key is not found.
fn warn_missing_flag_key(key: &str) {
    warn!("Requested flag key not found: {}", key);
    inc(
        FLAG_EVALUATION_ERROR_COUNTER,
        &[(
            "reason".to_string(),
            FLAG_MISSING_REQUESTED_FLAG_KEY.to_string(),
        )],
        1,
    );
}

/// Builds a HashMap from flag key to flag ID for efficient key-based lookups.
fn build_key_to_id(flags: &[FeatureFlag]) -> HashMap<String, i32> {
    flags.iter().map(|f| (f.key.clone(), f.id)).collect()
}

/// Increments the tombstone counter for a graph_utils operation.
fn inc_graph_tombstone(operation: &str) {
    inc(
        TOMBSTONE_COUNTER,
        &[
            ("namespace".to_string(), "feature_flags".to_string()),
            ("operation".to_string(), operation.to_string()),
            ("component".to_string(), "graph_utils".to_string()),
        ],
        1,
    );
}

#[derive(Debug, Clone)]
pub enum GraphError<Id> {
    MissingDependency(Id),
    CycleDetected(Id),
}

impl<Id> GraphError<Id> {
    /// Returns true if this error represents a cycle in the dependency graph.
    pub fn is_cycle(&self) -> bool {
        matches!(self, GraphError::CycleDetected(_))
    }
}

/// Trait for types that can provide their dependencies
pub trait DependencyProvider {
    type Id: Copy + Eq + std::hash::Hash + std::fmt::Display + Into<i64>;
    type Error;

    fn get_id(&self) -> Self::Id;

    fn extract_dependencies(&self) -> Result<HashSet<Self::Id>, Self::Error>;

    fn dependency_type() -> DependencyType;
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DependencyType {
    Flag,
    Cohort,
}

impl std::fmt::Display for DependencyType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            DependencyType::Flag => f.write_str("flag"),
            DependencyType::Cohort => f.write_str("cohort"),
        }
    }
}

/// A Directed Acyclic Graph that stores dependency relationships between items that implement DependencyProvider.
#[derive(Debug)]
pub struct DependencyGraph<T: DependencyProvider> {
    graph: DiGraph<T, ()>,
}

impl<T> DependencyGraph<T>
where
    T: DependencyProvider + Clone,
    T::Error: From<FlagError>,
{
    /// Creates a new DependencyGraph from a list of items, starting from an initial root item.
    /// The graph will include all dependencies of the initial item and their dependencies.
    ///
    /// Graph semantics:
    /// - Each node represents a flag or cohort.
    /// - Edges point from dependent to dependency:
    ///   A → B means "A depends on B" (A requires B to be evaluated first)
    ///   Note: Topological sorts expect edges to point from dependency to
    ///   dependent (not dependent to dependency as we do here). This is why
    ///   we reverse the output of the topological sort later.
    /// - This is a Directed Acyclic Graph (DAG); cycles are not allowed.
    ///
    /// Example dependency graph:
    /// ```text
    ///   A  B
    ///   ↓ ↘ ↓
    ///   C   D
    ///    ↘ ↙
    ///     E
    /// ```
    /// In this example:
    /// - A and B are root nodes (no dependencies).
    /// - C depends on A and B.
    /// - D depends on B.
    /// - E depends on C and D.
    ///
    /// Evaluation order:
    /// - Because edges are modeled as "dependent → dependency", the topological sort is
    ///   reversed to ensure dependencies are evaluated before dependents in the for_each_dependencies_first method.
    ///
    /// DAG invariants:
    /// - All dependencies must be evaluated before evaluating dependents.
    /// - Cycles indicate invalid configuration and must be rejected.
    pub fn new(root: T, pool: &[T]) -> Result<Self, T::Error> {
        let lookup: HashMap<T::Id, &T> = pool.iter().map(|item| (item.get_id(), item)).collect();

        let mut visited = HashSet::new();
        let mut queue = VecDeque::new();
        let root_id = root.get_id();
        queue.push_back(root_id);
        visited.insert(root_id);

        let mut nodes_to_include = vec![root];
        let mut edges: HashMap<T::Id, HashSet<T::Id>> = HashMap::with_capacity(pool.len());

        while let Some(current_id) = queue.pop_front() {
            let current_node = lookup.get(&current_id).ok_or_else(|| {
                FlagError::DependencyNotFound(T::dependency_type(), current_id.into())
            })?;

            let deps = current_node.extract_dependencies()?;
            for &dep in &deps {
                // Strict: fail if dependency is not present in pool
                let dep_node = lookup.get(&dep).ok_or_else(|| {
                    FlagError::DependencyNotFound(T::dependency_type(), dep.into())
                })?;

                if visited.insert(dep) {
                    nodes_to_include.push((*dep_node).clone());
                    queue.push_back(dep);
                }
            }
            edges.insert(current_id, deps);
        }

        let (graph, errors, _nodes_with_missing_deps) = Self::from_nodes(nodes_to_include, &edges)?;

        // Single-root constructor fails strictly on any error
        if !errors.is_empty() {
            // Return the first error as the failure reason
            match errors[0] {
                GraphError::MissingDependency(id) => {
                    return Err(
                        FlagError::DependencyNotFound(T::dependency_type(), id.into()).into(),
                    );
                }
                GraphError::CycleDetected(id) => {
                    return Err(FlagError::DependencyCycle(T::dependency_type(), id.into()).into());
                }
            }
        }

        Ok(graph)
    }

    /// Builds a multi-root dependency graph from nodes and a pre-computed edge
    /// map. Returns a partial graph even if there are errors (missing
    /// dependencies, cycles).
    #[allow(clippy::type_complexity)]
    pub fn from_nodes(
        nodes: Vec<T>,
        edges: &HashMap<T::Id, HashSet<T::Id>>,
    ) -> Result<(Self, Vec<GraphError<T::Id>>, HashSet<T::Id>), T::Error> {
        let mut graph = DiGraph::new();
        let mut id_map = HashMap::with_capacity(nodes.len());

        for node in nodes {
            let id = node.get_id();
            let idx = graph.add_node(node);
            id_map.insert(id, idx);
        }

        let mut errors = Vec::new();
        let mut nodes_with_direct_missing_deps: HashSet<NodeIndex> = HashSet::new();
        let empty_deps = HashSet::new();
        for (&node_id, &source_idx) in &id_map {
            let deps = edges.get(&node_id).unwrap_or(&empty_deps);
            for dep_id in deps {
                if let Some(target_idx) = id_map.get(dep_id) {
                    graph.add_edge(source_idx, *target_idx, ());
                } else {
                    errors.push(GraphError::MissingDependency(*dep_id));
                    nodes_with_direct_missing_deps.insert(source_idx);
                }
            }
        }

        Self::finalize(graph, errors, nodes_with_direct_missing_deps)
    }

    /// Shared post-processing: propagate missing deps transitively and remove cycles.
    #[allow(clippy::type_complexity)]
    fn finalize(
        mut graph: DiGraph<T, ()>,
        mut errors: Vec<GraphError<T::Id>>,
        nodes_with_direct_missing_deps: HashSet<NodeIndex>,
    ) -> Result<(Self, Vec<GraphError<T::Id>>, HashSet<T::Id>), T::Error> {
        let mut nodes_with_missing_deps: HashSet<T::Id> = HashSet::new();

        // Propagate missing dependency status transitively.
        // Any node that depends (directly or transitively) on a node with a missing
        // dependency should also be marked, so it evaluates to false (fail closed).
        Self::propagate_missing_deps_transitively(
            &graph,
            &nodes_with_direct_missing_deps,
            &mut nodes_with_missing_deps,
        );

        // Remove all cycles from the graph
        Self::remove_all_cycles(&mut graph, &mut errors);

        Ok((Self { graph }, errors, nodes_with_missing_deps))
    }

    /// Propagates missing dependency status transitively through the graph.
    /// Any node that depends (directly or transitively) on a node with a missing
    /// dependency will be added to the output set.
    fn propagate_missing_deps_transitively(
        graph: &DiGraph<T, ()>,
        nodes_with_direct_missing_deps: &HashSet<NodeIndex>,
        output: &mut HashSet<T::Id>,
    ) {
        use petgraph::Direction::Incoming;
        let mut visited: HashSet<NodeIndex> = HashSet::new();
        let mut stack: Vec<NodeIndex> = nodes_with_direct_missing_deps.iter().copied().collect();

        while let Some(idx) = stack.pop() {
            if visited.insert(idx) {
                // Add this node's ID to the output set
                output.insert(graph[idx].get_id());
                // Find all nodes that depend on this node (incoming edges = dependents)
                for dependent_idx in graph.neighbors_directed(idx, Incoming) {
                    if !visited.contains(&dependent_idx) {
                        stack.push(dependent_idx);
                    }
                }
            }
        }
    }

    /// Removes all cycles from the graph, adding cycle errors to the errors vector.
    /// This method modifies the graph in-place and continues until no cycles remain.
    fn remove_all_cycles(graph: &mut DiGraph<T, ()>, errors: &mut Vec<GraphError<T::Id>>) {
        // Validate cycles after full wiring - keep removing cycles until none remain
        while let Err(e) = toposort(&*graph, None) {
            let cycle_start_node = e.node_id();
            let cycle_id = graph[cycle_start_node].get_id();
            errors.push(GraphError::CycleDetected(cycle_id));
            // Remove cycle and its dependents
            Self::remove_node_and_dependents_from_graph(graph, cycle_start_node);
        }
    }

    fn remove_node_and_dependents_from_graph(
        graph: &mut DiGraph<T, ()>,
        node_idx: petgraph::graph::NodeIndex,
    ) {
        use petgraph::Direction::Incoming;
        let mut to_remove = Vec::new();
        let mut stack = vec![node_idx];
        let mut visited = HashSet::new();

        while let Some(idx) = stack.pop() {
            if visited.insert(idx) {
                to_remove.push(idx);
                // Add all nodes that depend on this node (incoming edges = dependents)
                for dependent in graph.neighbors_directed(idx, Incoming) {
                    if !visited.contains(&dependent) {
                        stack.push(dependent);
                    }
                }
            }
        }

        // Sort indices in descending order to avoid index shifting issues
        to_remove.sort_by(|a, b| b.cmp(a));

        for idx in to_remove {
            graph.remove_node(idx);
        }
    }

    /// Traverses the graph in reverse topological order (dependencies first);
    pub fn for_each_dependencies_first<F, R>(
        &self,
        mut callback: F,
    ) -> Result<HashMap<T::Id, R>, T::Error>
    where
        F: FnMut(&T, &HashMap<T::Id, R>, &mut R) -> Result<(), T::Error>,
        R: Default,
    {
        let sorted_nodes = toposort(&self.graph, None).map_err(|e| {
            let cycle_start_id = e.node_id();
            FlagError::DependencyCycle(T::dependency_type(), self.get_node_id(cycle_start_id))
        })?;

        let mut results = HashMap::new();

        for node in sorted_nodes.into_iter().rev() {
            let item = &self.graph[node];
            let mut result = R::default();
            callback(item, &results, &mut result)?;
            results.insert(item.get_id(), result);
        }

        Ok(results)
    }

    /// Computes evaluation stages where each stage contains nodes that can be safely evaluated in parallel.
    ///
    /// This is a "leaves-first" topological batching algorithm, ideal for feature flag evaluation.
    ///
    /// Each stage consists of all nodes whose dependencies have already been evaluated.
    /// Items in earlier stages must be evaluated before items in later stages.
    ///
    /// Graph edge semantics reminder:
    /// - Edges point from dependent → dependency:
    ///   A → B means "A depends on B" (A requires B to be evaluated first)
    /// - Therefore:
    ///     - Outgoing edges = dependencies
    ///     - Incoming edges = dependents (nodes that require this node)
    ///
    /// The algorithm works by repeatedly finding all nodes that have no remaining dependencies (out-degree == 0),
    /// evaluating them as one stage, and then decrementing the remaining dependencies of their dependents.
    pub fn evaluation_stages(&self) -> Result<Vec<Vec<&T>>, T::Error> {
        let out_degree = self.build_evaluation_maps();
        Self::compute_stages(&self.graph, out_degree)
    }

    /// Like `evaluation_stages`, but consumes the graph and returns owned values.
    /// Avoids cloning flags when they need to be moved into another context (e.g. rayon).
    pub fn into_evaluation_stages(self) -> Result<Vec<Vec<T>>, T::Error> {
        let out_degree = self.build_evaluation_maps();
        let stage_indices = Self::compute_stage_indices(&self.graph, out_degree)?;
        let (nodes, _) = self.graph.into_nodes_edges();
        let mut node_slots: Vec<Option<T>> = nodes.into_iter().map(|n| Some(n.weight)).collect();

        Ok(stage_indices
            // SAFETY: compute_stage_indices guarantees each node appears in exactly one stage
            .into_iter()
            .map(|stage| {
                stage
                    .into_iter()
                    .map(|idx| {
                        node_slots[idx.index()]
                            .take()
                            .expect("node used in multiple stages")
                    })
                    .collect()
            })
            .collect())
    }

    /// Returns an iterator over all nodes (items) in the graph.
    pub fn iter_nodes(&self) -> impl Iterator<Item = &T> {
        self.graph.node_indices().map(|idx| &self.graph[idx])
    }

    fn build_evaluation_maps(&self) -> HashMap<NodeIndex, usize> {
        use petgraph::Direction::Outgoing;
        let node_count = self.graph.node_count();
        let mut out_degree: HashMap<NodeIndex, usize> = HashMap::with_capacity(node_count);
        for node_idx in self.graph.node_indices() {
            let deg = self.graph.edges_directed(node_idx, Outgoing).count();
            out_degree.insert(node_idx, deg);
        }
        out_degree
    }

    fn compute_stage_indices(
        graph: &DiGraph<T, ()>,
        mut out_degree: HashMap<NodeIndex, usize>,
    ) -> Result<Vec<Vec<NodeIndex>>, T::Error> {
        use petgraph::Direction::Incoming;

        // Kahn's algorithm: seed queue with all zero-degree nodes, then push
        // nodes as their degree drops to zero. O(V+E) vs O(V²) repeated scans.
        let mut queue: VecDeque<NodeIndex> = out_degree
            .iter()
            .filter(|(_, &deg)| deg == 0)
            .map(|(&idx, _)| idx)
            .collect();

        let mut stages = Vec::new();
        while !queue.is_empty() {
            let current_stage: Vec<NodeIndex> = queue.drain(..).collect();
            for &node_idx in &current_stage {
                out_degree.remove(&node_idx);
                for parent in graph.neighbors_directed(node_idx, Incoming) {
                    if let Some(deg) = out_degree.get_mut(&parent) {
                        *deg -= 1;
                        if *deg == 0 {
                            queue.push_back(parent);
                        }
                    }
                }
            }
            stages.push(current_stage);
        }

        if let Some((&cycle_idx, _)) = out_degree.iter().next() {
            let cycle_id: i64 = graph[cycle_idx].get_id().into();
            return Err(FlagError::DependencyCycle(T::dependency_type(), cycle_id).into());
        }

        Ok(stages)
    }

    fn compute_stages(
        graph: &DiGraph<T, ()>,
        out_degree: HashMap<NodeIndex, usize>,
    ) -> Result<Vec<Vec<&T>>, T::Error> {
        let stage_indices = Self::compute_stage_indices(graph, out_degree)?;
        Ok(stage_indices
            .into_iter()
            .map(|stage| stage.into_iter().map(|idx| &graph[idx]).collect())
            .collect())
    }

    /// Helper to get a node's ID as an i64
    #[inline]
    fn get_node_id(&self, index: petgraph::graph::NodeIndex) -> i64 {
        self.graph[index].get_id().into()
    }

    #[cfg(test)]
    pub(crate) fn node_count(&self) -> usize {
        self.graph.node_count()
    }

    #[cfg(test)]
    pub(crate) fn edge_count(&self) -> usize {
        self.graph.edge_count()
    }

    #[cfg(test)]
    pub(crate) fn contains_node(&self, id: T::Id) -> bool {
        self.graph
            .node_indices()
            .any(|idx| self.graph[idx].get_id() == id)
    }

    #[cfg(test)]
    pub(crate) fn get_all_nodes(&self) -> Vec<&T> {
        self.graph
            .node_indices()
            .map(|idx| &self.graph[idx])
            .collect()
    }
}

// TODO: Remove these #[cfg(test)] items (DependencyGraphResult, build_dependency_graph,
// FilteredGraphResult, filter_graph_by_keys) and the petgraph dependency once the
// precomputed path is validated in production and the fallback path is removed.
#[cfg(test)]
/// Result of building a dependency graph, including the graph, errors, and flags with missing dependencies.
pub struct DependencyGraphResult {
    /// The dependency graph (may include nodes with missing dependencies)
    pub graph: DependencyGraph<FeatureFlag>,
    /// Errors encountered during construction (missing dependencies, cycles)
    pub errors: Vec<GraphError<i32>>,
    /// Set of flag IDs that have missing dependencies and should evaluate to false
    pub flags_with_missing_deps: HashSet<i32>,
}

#[cfg(test)]
/// Builds a dependency graph for flag evaluation.
/// Returns None only for fatal errors. Partial errors (cycles, missing dependencies)
/// are returned in the result and nodes with missing dependencies are kept in the graph.
///
/// Only includes flags reachable from the seed set via their transitive dependency closure.
/// The seed set excludes flags in `filtered_out_flag_ids` (inactive, deleted, survey-excluded,
/// runtime-mismatched, and tag-filtered). Filtered-out flags pulled in as dependencies are
/// included as nodes but their own dependencies are not followed, since they evaluate to false.
pub fn build_dependency_graph(
    feature_flags: &crate::flags::flag_models::FeatureFlagList,
    team_id: common_types::TeamId,
) -> Option<DependencyGraphResult> {
    // Build lookup table: flag_id -> &FeatureFlag (no cloning).
    // If duplicate IDs exist, the last flag wins and we log a warning.
    let mut lookup: HashMap<i32, &FeatureFlag> = HashMap::with_capacity(feature_flags.flags.len());
    for flag in &feature_flags.flags {
        if lookup.insert(flag.id, flag).is_some() {
            warn!(
                team_id = team_id,
                flag_id = flag.id,
                "duplicate flag ID in FeatureFlagList, last occurrence wins"
            );
        }
    }

    // Seed set: flags not excluded by the request-scoped filter.
    // filtered_out_flag_ids already contains inactive, deleted, and other
    // request-specific exclusions, so one check covers all categories.
    let flag_count = feature_flags.flags.len();
    let mut visited: HashSet<i32> = HashSet::with_capacity(flag_count);
    let mut queue: VecDeque<i32> = VecDeque::with_capacity(flag_count);
    for flag in &feature_flags.flags {
        if !feature_flags.filtered_out_flag_ids.contains(&flag.id) {
            visited.insert(flag.id);
            queue.push_back(flag.id);
        }
    }

    // BFS to compute transitive dependency closure, collecting edges along the way.
    // Capacity is based on the seed set size since that's the minimum number of entries.
    let mut edges: HashMap<i32, HashSet<i32>> = HashMap::with_capacity(visited.len());
    while let Some(current_id) = queue.pop_front() {
        let Some(flag) = lookup.get(&current_id) else {
            // Invariant: every queued ID comes from lookup's keys. Fire tombstone and skip.
            inc_graph_tombstone("bfs_closure_lookup_miss");
            continue;
        };
        // Filtered-out flags (inactive, deleted, survey-excluded, etc.) are
        // pre-seeded as `false` during evaluation, so their own dependencies
        // are irrelevant. extract_dependencies() already returns empty for
        // !active || deleted; this extends the same treatment to all
        // filtered-out categories (runtime mismatch, tag filter, etc.).
        if feature_flags.filtered_out_flag_ids.contains(&current_id) {
            edges.insert(current_id, HashSet::new());
            continue;
        }
        match flag.extract_dependencies() {
            Ok(deps) => {
                // Only follow deps that exist in the flag list; missing deps are
                // left in `edges` so from_nodes can report them.
                for dep_id in &deps {
                    if lookup.contains_key(dep_id) && visited.insert(*dep_id) {
                        queue.push_back(*dep_id);
                    }
                }
                edges.insert(current_id, deps);
            }
            Err(e) => {
                log_dependency_graph_operation_error(
                    "extract dependencies during closure",
                    &e,
                    team_id,
                );
                return None;
            }
        }
    }

    // Clone only the flags in the closure set
    let closure_flags: Vec<FeatureFlag> = feature_flags
        .flags
        .iter()
        .filter(|f| visited.contains(&f.id))
        .cloned()
        .collect();

    let (graph, errors, flags_with_missing_deps) =
        match DependencyGraph::from_nodes(closure_flags, &edges) {
            Ok(result) => result,
            Err(e) => {
                log_dependency_graph_operation_error("build global dependency graph", &e, team_id);
                return None;
            }
        };

    if !errors.is_empty() {
        log_dependency_graph_construction_errors(&errors, team_id);
    }

    Some(DependencyGraphResult {
        graph,
        errors,
        flags_with_missing_deps,
    })
}

#[cfg(test)]
/// Result of filtering a dependency graph.
pub struct FilteredGraphResult {
    /// The filtered dependency graph
    pub graph: DependencyGraph<FeatureFlag>,
    /// Subset of flags_with_missing_deps that are in the filtered graph
    pub flags_with_missing_deps: HashSet<i32>,
}

#[cfg(test)]
/// Filters a dependency graph to include only the requested flags and their dependencies.
/// Also filters the flags_with_missing_deps set to only include flags in the filtered graph.
/// Returns None if:
/// - There were errors during filtering
/// - The global_graph's internal state is corrupted
pub fn filter_graph_by_keys(
    global_graph: &DependencyGraph<FeatureFlag>,
    requested_keys: &[String],
    flags_with_missing_deps: &HashSet<i32>,
) -> Option<FilteredGraphResult> {
    use petgraph::visit::EdgeRef;
    let mut nodes_to_include = HashSet::new();

    // Build an index from flag keys to node indices for O(1) lookups
    let key_to_node: HashMap<&str, petgraph::graph::NodeIndex> = global_graph
        .graph
        .node_indices()
        .map(|idx| (global_graph.graph[idx].key.as_str(), idx))
        .collect();

    // For each requested flag, traverse the global graph to collect dependencies.
    // Share visited state across keys to avoid redundant traversals when keys
    // share dependency subtrees.
    let mut visited = HashSet::new();
    for key in requested_keys {
        // Find the flag in the global graph using the index
        let node_idx = key_to_node.get(key.as_str());

        if let Some(&start_idx) = node_idx {
            if !visited.insert(start_idx) {
                // Already traversed from a previous key
                nodes_to_include.insert(start_idx);
                continue;
            }

            // Use BFS to collect all reachable nodes (dependencies) from this flag
            let mut queue = std::collections::VecDeque::new();
            queue.push_back(start_idx);

            while let Some(current_idx) = queue.pop_front() {
                nodes_to_include.insert(current_idx);

                // Add all dependencies (outgoing edges) to the queue
                for neighbor_idx in global_graph
                    .graph
                    .neighbors_directed(current_idx, petgraph::Direction::Outgoing)
                {
                    if visited.insert(neighbor_idx) {
                        queue.push_back(neighbor_idx);
                    }
                }
            }
        } else {
            warn_missing_flag_key(key);
        }
    }

    // Create a new graph with only the filtered nodes
    let mut filtered_graph = DiGraph::new();
    let mut node_mapping = HashMap::new();
    let mut filtered_missing_deps = HashSet::new();

    for &node_idx in &nodes_to_include {
        let flag = global_graph.graph[node_idx].clone();
        if flags_with_missing_deps.contains(&flag.id) {
            filtered_missing_deps.insert(flag.id);
        }
        let new_idx = filtered_graph.add_node(flag);
        node_mapping.insert(node_idx, new_idx);
    }

    // Add all the edges between the included nodes
    for &node_idx in &nodes_to_include {
        if let Some(&new_source_idx) = node_mapping.get(&node_idx) {
            for edge in global_graph
                .graph
                .edges_directed(node_idx, petgraph::Direction::Outgoing)
            {
                let target_idx = edge.target();
                if let Some(&new_target_idx) = node_mapping.get(&target_idx) {
                    filtered_graph.add_edge(new_source_idx, new_target_idx, ());
                }
            }
        }
    }

    Some(FilteredGraphResult {
        graph: DependencyGraph {
            graph: filtered_graph,
        },
        flags_with_missing_deps: filtered_missing_deps,
    })
}

/// Pre-computed dependency graph data, built once when flags are loaded from cache.
/// All fields are derived deterministically from the flag list.
#[derive(Debug)]
pub struct PrecomputedDependencyGraph {
    /// Topologically sorted evaluation stages. Each inner Vec contains flags
    /// that can be evaluated in parallel (all their dependencies appear in
    /// earlier stages).
    pub evaluation_stages: Vec<Vec<FeatureFlag>>,

    /// Flag IDs whose dependencies are missing or transitively broken.
    /// On the precomputed path, this includes cycle participants (Django merges
    /// them). On the graph fallback path, cycle participants are removed from
    /// stages separately. Both paths evaluate these flags as false (fail closed).
    pub flags_with_missing_deps: HashSet<i32>,

    /// For each flag ID, the set of all transitive dependency flag IDs.
    /// Only populated on the graph fallback path for use by `filter_stages_by_keys`.
    pub(crate) transitive_deps: HashMap<i32, HashSet<i32>>,

    /// Mapping from flag key to flag ID, for efficient key-based lookups.
    /// Only populated on the graph fallback path for use by `filter_stages_by_keys`.
    pub(crate) key_to_id: HashMap<String, i32>,

    /// Number of flags affected by dependency errors (missing deps + cycles).
    pub error_count: usize,

    /// Whether any graph construction errors were dependency cycles.
    pub has_cycle_errors: bool,

    /// True when built via the graph fallback path (no precomputed metadata).
    /// The caller uses this to decide whether post-build filtering via
    /// `filter_stages_by_keys` is needed.
    pub is_graph_fallback: bool,
}

/// Result of filtering pre-computed stages by requested flag keys.
#[derive(Debug)]
pub struct FilteredStagesResult {
    /// Filtered evaluation stages containing only the requested flags and their dependencies.
    pub evaluation_stages: Vec<Vec<FeatureFlag>>,
    /// Subset of flags_with_missing_deps that are relevant to the filtered stages.
    pub flags_with_missing_deps: HashSet<i32>,
}

impl PrecomputedDependencyGraph {
    /// Builds a `PrecomputedDependencyGraph` from a flag list.
    /// Uses the fast path when Django-precomputed `evaluation_metadata` is present,
    /// falls back to full graph construction otherwise.
    ///
    /// When `flag_keys` is provided on the precomputed path, only the requested flags
    /// and their transitive dependencies are cloned into stages, avoiding allocation
    /// of unneeded `FeatureFlag` structs. On the fallback (graph) path, `flag_keys` is
    /// ignored — the caller must use `filter_stages_by_keys` after build.
    ///
    /// Returns `None` only for fatal errors (same semantics as `build_dependency_graph`).
    pub fn build(
        feature_flags: &crate::flags::flag_models::FeatureFlagList,
        team_id: common_types::TeamId,
        flag_keys: Option<&[String]>,
    ) -> Option<Self> {
        let (path, result) =
            if let Some(ref evaluation_metadata) = feature_flags.evaluation_metadata {
                let labels = [(
                    "path".to_string(),
                    FLAG_DEPENDENCY_GRAPH_PATH_PRECOMPUTED.to_string(),
                )];
                let _timer = timing_guard(FLAG_DEPENDENCY_GRAPH_BUILD_TIME, &labels);
                (
                    FLAG_DEPENDENCY_GRAPH_PATH_PRECOMPUTED,
                    Self::build_from_precomputed(
                        &feature_flags.flags,
                        evaluation_metadata,
                        &feature_flags.filtered_out_flag_ids,
                        flag_keys,
                    ),
                )
            } else {
                let labels = [(
                    "path".to_string(),
                    FLAG_DEPENDENCY_GRAPH_PATH_GRAPH.to_string(),
                )];
                let _timer = timing_guard(FLAG_DEPENDENCY_GRAPH_BUILD_TIME, &labels);
                (
                    FLAG_DEPENDENCY_GRAPH_PATH_GRAPH,
                    Self::build_from_graph(
                        &feature_flags.flags,
                        &feature_flags.filtered_out_flag_ids,
                        team_id,
                    ),
                )
            };
        inc(
            FLAG_DEPENDENCY_GRAPH_BUILD_COUNTER,
            &[("path".to_string(), path.to_string())],
            1,
        );
        result
    }

    /// Fast path: consumes the top-level `EvaluationMetadata` directly.
    /// No Kahn's algorithm, no per-flag scanning, no ID→key conversion loops.
    ///
    /// When `flag_keys` is provided, only the requested flags and their transitive
    /// dependencies are cloned into stages, avoiding allocation of unneeded structs.
    /// Global stats (`error_count`, `has_cycle_errors`) always reflect the full flag set.
    fn build_from_precomputed(
        flags: &[FeatureFlag],
        evaluation_metadata: &crate::flags::flag_models::EvaluationMetadata,
        filtered_out_flag_ids: &HashSet<i32>,
        flag_keys: Option<&[String]>,
    ) -> Option<Self> {
        let id_to_flag: HashMap<i32, &FeatureFlag> = flags.iter().map(|f| (f.id, f)).collect();

        // When flag_keys is specified, compute the set of needed flag IDs upfront
        // so we only clone flags that will actually be evaluated.
        let needed_ids: Option<HashSet<i32>> = flag_keys.map(|keys| {
            let key_to_id: HashMap<&str, i32> =
                flags.iter().map(|f| (f.key.as_str(), f.id)).collect();
            let mut ids = HashSet::new();
            for key in keys {
                if let Some(&id) = key_to_id.get(key.as_str()) {
                    ids.insert(id);
                    if let Some(dep_ids) = evaluation_metadata.transitive_deps.get(&id) {
                        ids.extend(dep_ids);
                    }
                } else {
                    warn_missing_flag_key(key);
                }
            }
            ids
        });

        // When flag_keys is None, all non-filtered-out flags are needed.
        let is_needed = |id: &i32| needed_ids.as_ref().is_none_or(|ids| ids.contains(id));

        // Count non-filtered-out IDs across all stages for the cycle count computation.
        let global_flags_in_stages_count: usize = evaluation_metadata
            .dependency_stages
            .iter()
            .flat_map(|stage| stage.iter())
            .filter(|id| !filtered_out_flag_ids.contains(id))
            .count();

        // Assemble stages from pre-grouped IDs, excluding runtime-filtered flags
        // and (when flag_keys is specified) flags not in the needed set.
        let evaluation_stages: Vec<Vec<FeatureFlag>> = evaluation_metadata
            .dependency_stages
            .iter()
            .filter_map(|stage_ids| {
                let stage: Vec<FeatureFlag> = stage_ids
                    .iter()
                    .filter(|id| !filtered_out_flag_ids.contains(id))
                    .filter(|id| is_needed(id))
                    .filter_map(|id| id_to_flag.get(id).map(|f| (*f).clone()))
                    .collect();
                (!stage.is_empty()).then_some(stage)
            })
            .collect();

        let flags_with_missing_deps: HashSet<i32> = evaluation_metadata
            .flags_with_missing_deps
            .iter()
            .copied()
            .filter(|id| !filtered_out_flag_ids.contains(id))
            .filter(|id| is_needed(id))
            .collect();

        // Django's Kahn's algorithm guarantees: a flag appears in dependency_stages
        // iff it reaches zero in-degree (i.e., is not a cycle participant).
        // Therefore: total flags - filtered out - staged = cycle participants.
        // saturating_sub guards against filtered_out_flag_ids containing IDs
        // not present in the flags slice.
        let cycle_count = flags
            .len()
            .saturating_sub(filtered_out_flag_ids.len())
            .saturating_sub(global_flags_in_stages_count);

        // When flag_keys was provided, filtering already happened during construction
        // so transitive_deps and key_to_id are not needed on the struct.
        // When flag_keys is None, populate them for cross-validation tests that
        // compare precomputed and fallback paths.
        let (transitive_deps, key_to_id) = if flag_keys.is_some() {
            (HashMap::new(), HashMap::new())
        } else {
            (
                evaluation_metadata.transitive_deps.clone(),
                build_key_to_id(flags),
            )
        };

        // Django's flags_with_missing_deps already includes cycle participants
        // (in_degree > 0 after Kahn's), so don't add cycle_count separately.
        Some(Self {
            evaluation_stages,
            error_count: flags_with_missing_deps.len(),
            has_cycle_errors: cycle_count > 0,
            flags_with_missing_deps,
            transitive_deps,
            key_to_id,
            is_graph_fallback: false,
        })
    }

    /// Fallback path: builds a full petgraph-based dependency graph when
    /// precomputed data is absent (old cache format or PG fallback).
    fn build_from_graph(
        flags: &[FeatureFlag],
        filtered_out_flag_ids: &HashSet<i32>,
        team_id: common_types::TeamId,
    ) -> Option<Self> {
        // Extract edges from each flag's property filters.
        // Filtered-out flags (runtime mismatch, tag filter, etc.) get empty
        // edges so their dependencies aren't followed, preventing false cycles.
        // Note: unlike the old BFS-based build_dependency_graph, this includes
        // all filtered-out flags as isolated nodes rather than only reachable
        // ones. This is safe — unreachable nodes end up in stage 0 and are
        // skipped during evaluation.
        let mut edges: HashMap<i32, HashSet<i32>> = HashMap::with_capacity(flags.len());
        for flag in flags {
            if filtered_out_flag_ids.contains(&flag.id) {
                edges.insert(flag.id, HashSet::new());
                continue;
            }
            match flag.extract_dependencies() {
                Ok(deps) => {
                    edges.insert(flag.id, deps);
                }
                Err(e) => {
                    log_dependency_graph_operation_error(
                        "extract dependencies for graph fallback",
                        &e,
                        team_id,
                    );
                    return None;
                }
            }
        }

        let (graph, errors, flags_with_missing_deps) =
            match DependencyGraph::from_nodes(flags.to_vec(), &edges) {
                Ok(result) => result,
                Err(e) => {
                    log_dependency_graph_operation_error(
                        "build global dependency graph",
                        &e,
                        team_id,
                    );
                    return None;
                }
            };

        if !errors.is_empty() {
            log_dependency_graph_construction_errors(&errors, team_id);
        }

        let cycle_count = errors.iter().filter(|e| e.is_cycle()).count();
        let has_cycle_errors = cycle_count > 0;
        let error_count = flags_with_missing_deps.len() + cycle_count;
        let transitive_deps = Self::build_transitive_deps_map_from_graph(&graph);
        let key_to_id = build_key_to_id(flags);

        let evaluation_stages = match graph.into_evaluation_stages() {
            Ok(stages) => stages,
            Err(e) => {
                log_dependency_graph_operation_error("get evaluation stages", &e, team_id);
                return None;
            }
        };

        Some(Self {
            evaluation_stages,
            flags_with_missing_deps,
            transitive_deps,
            key_to_id,
            error_count,
            has_cycle_errors,
            is_graph_fallback: true,
        })
    }

    /// Filters evaluation stages to only include the requested flags and their
    /// transitive dependencies. Consumes `self` to move (not clone) flags into
    /// the result. Uses ID-based filtering for speed.
    ///
    /// Used by the fallback (graph) path where flag_keys filtering cannot happen
    /// during construction. The precomputed path filters during build instead.
    pub fn filter_stages_by_keys(self, requested_keys: &[String]) -> FilteredStagesResult {
        debug_assert!(
            self.is_graph_fallback,
            "filter_stages_by_keys should only be called on graph fallback path"
        );
        let mut needed_ids: HashSet<i32> = HashSet::new();
        for key in requested_keys {
            if let Some(&id) = self.key_to_id.get(key.as_str()) {
                needed_ids.insert(id);
                if let Some(dep_ids) = self.transitive_deps.get(&id) {
                    needed_ids.extend(dep_ids);
                }
            } else {
                warn_missing_flag_key(key);
            }
        }

        // Filter stages by flag ID, dropping empty stages.
        // Uses into_iter to move flags rather than cloning them.
        let evaluation_stages: Vec<Vec<FeatureFlag>> = self
            .evaluation_stages
            .into_iter()
            .filter_map(|stage| {
                let filtered: Vec<FeatureFlag> = stage
                    .into_iter()
                    .filter(|flag| needed_ids.contains(&flag.id))
                    .collect();
                (!filtered.is_empty()).then_some(filtered)
            })
            .collect();

        // needed_ids is the exact set of flags that could appear in filtered stages,
        // so intersecting with it avoids a second pass over the stages.
        let flags_with_missing_deps: HashSet<i32> = self
            .flags_with_missing_deps
            .intersection(&needed_ids)
            .copied()
            .collect();

        FilteredStagesResult {
            evaluation_stages,
            flags_with_missing_deps,
        }
    }

    /// Builds a map from each flag ID to the set of all its transitive dependency IDs.
    /// Used by the fallback (petgraph) path. Uses memoization to avoid redundant
    /// graph traversals, though set copying makes worst case O(V^2) for chains.
    fn build_transitive_deps_map_from_graph(
        graph: &DependencyGraph<FeatureFlag>,
    ) -> HashMap<i32, HashSet<i32>> {
        use petgraph::algo::toposort;
        use petgraph::Direction::Outgoing;
        let inner = &graph.graph;

        let mut memo: HashMap<NodeIndex, HashSet<i32>> = HashMap::new();

        // Process in reverse topological order so dependencies are computed
        // before the nodes that depend on them. If toposort fails (cycle),
        // fall back to natural node order — cycles were already removed from
        // the graph by this point, so this is just a safety net.
        let order: Vec<NodeIndex> = match toposort(inner, None) {
            Ok(mut sorted) => {
                sorted.reverse();
                sorted
            }
            Err(_) => inner.node_indices().collect(),
        };

        for node_idx in order {
            let mut deps = HashSet::new();
            for neighbor in inner.neighbors_directed(node_idx, Outgoing) {
                let dep_id = inner[neighbor].id;
                deps.insert(dep_id);
                // Reuse already-computed transitive deps for this neighbor
                if let Some(transitive) = memo.get(&neighbor) {
                    deps.extend(transitive);
                }
            }
            memo.insert(node_idx, deps);
        }

        memo.into_iter()
            .map(|(idx, deps)| (inner[idx].id, deps))
            .collect()
    }
}

/// Handles errors during dependency graph operations.
pub fn log_dependency_graph_operation_error(
    error_type: &str,
    error: &dyn std::fmt::Debug,
    team_id: common_types::TeamId,
) {
    tracing::error!("Failed to {} for team {}: {:?}", error_type, team_id, error);
    inc(
        FLAG_EVALUATION_ERROR_COUNTER,
        &[
            (
                "reason".to_string(),
                format!("{}_error", error_type.replace(" ", "_")),
            ),
            ("team_id".to_string(), team_id.to_string()),
        ],
        1,
    );
}

/// Handles errors found during dependency graph construction.
pub fn log_dependency_graph_construction_errors(
    errors: &[GraphError<i32>],
    team_id: common_types::TeamId,
) {
    for error in errors {
        let failure_type = match error {
            GraphError::MissingDependency(_) => "flag_dependency_missing",
            GraphError::CycleDetected(_) => "flag_dependency_cycle",
        };

        inc_graph_tombstone(failure_type);
    }

    tracing::warn!(
        "There were errors building the feature flag dependency graph for team {}. Will attempt to evaluate the rest of the flags: {:?}",
        team_id, errors
    );
}

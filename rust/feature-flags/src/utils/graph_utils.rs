use std::collections::{HashMap, HashSet, VecDeque};

use petgraph::{
    algo::toposort,
    graph::{DiGraph, NodeIndex},
};

use crate::api::errors::FlagError;
use crate::flags::flag_models::FeatureFlag;
use crate::metrics::consts::{
    FLAG_DEPENDENCY_GRAPH_BUILD_COUNTER, FLAG_DEPENDENCY_GRAPH_BUILD_TIME,
    FLAG_EVALUATION_ERROR_COUNTER, FLAG_MISSING_REQUESTED_FLAG_KEY,
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

/// Result of computing evaluation metadata from a dependency graph.
/// Contains staged evaluation order, transitive dependencies, and
/// nodes with missing or broken dependencies.
#[derive(Debug, Clone)]
pub struct EvaluationResult<Id: Copy + Eq + std::hash::Hash> {
    /// Node IDs grouped by evaluation stage. Stage 0 = leaves (no deps).
    /// Each inner Vec is sorted by ID for determinism.
    pub stages: Vec<Vec<Id>>,
    /// Node ID → set of all transitive dependency node IDs for nodes remaining
    /// in the graph. Nodes removed before evaluation (e.g. cycle participants)
    /// will be absent — callers should backfill empty entries if needed.
    pub transitive_deps: HashMap<Id, HashSet<Id>>,
    /// Sorted list of node IDs with missing, cyclic, or transitively broken deps.
    pub nodes_with_missing_deps: Vec<Id>,
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

    /// Computes evaluation stages, transitive dependencies, and missing-dep propagation
    /// in a single pass over the topologically sorted stages.
    ///
    /// `nodes_with_missing_deps_set` contains IDs already known to have missing deps
    /// (e.g. nodes removed during cycle detection, or nodes with external missing deps).
    /// This method propagates that status: any node depending on a missing-dep node
    /// is also marked as having missing deps.
    pub fn compute_evaluation_metadata(
        &self,
        nodes_with_missing_deps_set: &HashSet<T::Id>,
    ) -> Result<EvaluationResult<T::Id>, T::Error>
    where
        T::Id: Ord,
    {
        use petgraph::Direction::Outgoing;

        let out_degree = self.build_evaluation_maps();
        let stage_indices = Self::compute_stage_indices(&self.graph, out_degree)?;

        // Build NodeIndex → Id lookup
        let node_id = |idx: NodeIndex| -> T::Id { self.graph[idx].get_id() };

        let mut transitive_deps: HashMap<T::Id, HashSet<T::Id>> =
            HashMap::with_capacity(self.graph.node_count());
        let mut has_missing: HashSet<T::Id> = nodes_with_missing_deps_set.clone();
        let mut stages: Vec<Vec<T::Id>> = Vec::with_capacity(stage_indices.len());

        for stage in &stage_indices {
            let mut stage_ids: Vec<T::Id> = Vec::with_capacity(stage.len());

            for &node_idx in stage {
                let id = node_id(node_idx);
                stage_ids.push(id);

                // Collect transitive deps: union of {direct_dep} ∪ transitive_deps[direct_dep]
                // This is safe because all deps appear in earlier stages.
                let mut my_deps = HashSet::new();
                for dep_idx in self.graph.neighbors_directed(node_idx, Outgoing) {
                    let dep_id = node_id(dep_idx);
                    my_deps.insert(dep_id);
                    if let Some(dep_transitive) = transitive_deps.get(&dep_id) {
                        my_deps.extend(dep_transitive);
                    }
                    // Propagate missing status
                    if has_missing.contains(&dep_id) {
                        has_missing.insert(id);
                    }
                }
                transitive_deps.insert(id, my_deps);
            }

            // Sort each stage for determinism
            stage_ids.sort();
            stages.push(stage_ids);
        }

        let mut nodes_with_missing_deps: Vec<T::Id> = has_missing.into_iter().collect();
        nodes_with_missing_deps.sort();

        Ok(EvaluationResult {
            stages,
            transitive_deps,
            nodes_with_missing_deps,
        })
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
}

/// Pre-computed dependency graph data, built once when flags are loaded from cache.
/// All fields are derived deterministically from the flag list and Django's
/// pre-computed `EvaluationMetadata`.
#[derive(Debug)]
pub struct PrecomputedDependencyGraph {
    /// Topologically sorted evaluation stages. Each inner Vec contains flags
    /// that can be evaluated in parallel (all their dependencies appear in
    /// earlier stages).
    pub evaluation_stages: Vec<Vec<FeatureFlag>>,

    /// Flag IDs whose dependencies are missing or transitively broken.
    /// Includes cycle participants (Django merges them into this set).
    /// These flags evaluate to false (fail closed).
    pub flags_with_missing_deps: HashSet<i32>,

    /// Number of flags affected by dependency errors (missing deps + cycles).
    pub error_count: usize,

    /// Whether any graph construction errors were dependency cycles.
    pub has_cycle_errors: bool,
}

impl PrecomputedDependencyGraph {
    /// Builds a `PrecomputedDependencyGraph` from a flag list using Django's
    /// pre-computed `EvaluationMetadata`.
    ///
    /// When `flag_keys` is provided, only the requested flags and their transitive
    /// dependencies are cloned into stages, avoiding allocation of unneeded
    /// `FeatureFlag` structs.
    pub fn build(
        feature_flags: &crate::flags::flag_models::FeatureFlagList,
        flag_keys: Option<&[String]>,
    ) -> Self {
        let _timer = timing_guard(FLAG_DEPENDENCY_GRAPH_BUILD_TIME, &[]);

        let result = Self::build_from_precomputed(
            &feature_flags.flags,
            &feature_flags.evaluation_metadata,
            &feature_flags.filtered_out_flag_ids,
            flag_keys,
        );

        inc(FLAG_DEPENDENCY_GRAPH_BUILD_COUNTER, &[], 1);
        result
    }

    /// Consumes the top-level `EvaluationMetadata` directly.
    ///
    /// When `flag_keys` is provided, only the requested flags and their transitive
    /// dependencies are cloned into stages, avoiding allocation of unneeded structs.
    /// Global stats (`error_count`, `has_cycle_errors`) always reflect the full flag set.
    fn build_from_precomputed(
        flags: &[FeatureFlag],
        evaluation_metadata: &crate::flags::flag_models::EvaluationMetadata,
        filtered_out_flag_ids: &HashSet<i32>,
        flag_keys: Option<&[String]>,
    ) -> Self {
        let id_to_flag: HashMap<i32, &FeatureFlag> = flags.iter().map(|f| (f.id, f)).collect();

        // When flag_keys is specified, compute the set of needed flag IDs upfront so we
        // only clone flags that will actually be evaluated. On the PG fallback path,
        // single_stage() populates per-flag empty dep sets so independent-flag filtering
        // still works. If transitive_deps is truly empty, we can't filter at all.
        let needed_ids: Option<HashSet<i32>> = if evaluation_metadata.transitive_deps.is_empty() {
            None
        } else {
            flag_keys.map(|keys| {
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
            })
        };

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

        // Django's flags_with_missing_deps already includes cycle participants
        // (in_degree > 0 after Kahn's), so don't add cycle_count separately.
        Self {
            evaluation_stages,
            error_count: flags_with_missing_deps.len(),
            has_cycle_errors: cycle_count > 0,
            flags_with_missing_deps,
        }
    }
}

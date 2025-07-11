use std::collections::{HashMap, HashSet, VecDeque};

use petgraph::{
    algo::toposort,
    graph::{DiGraph, NodeIndex},
    visit::EdgeRef,
};

use crate::api::errors::FlagError;
use crate::flags::flag_models::FeatureFlag;
use crate::metrics::consts::FLAG_EVALUATION_ERROR_COUNTER;
use common_metrics::inc;
use tracing::warn;

#[derive(Debug, Clone)]
pub enum GraphError<Id> {
    MissingDependency(Id),
    CycleDetected(Id),
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
    ///     A → B means "A depends on B" (A requires B to be evaluated first)
    ///     Note: Topological sorts expect edges to point from dependency to
    ///     dependent (not dependent to dependency as we do here). This is why
    ///     we reverse the output of the topological sort later.
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
        let lookup: HashMap<T::Id, T> = pool
            .iter()
            .map(|item| (item.get_id(), item.clone()))
            .collect();

        let mut visited = HashSet::new();
        let mut queue = VecDeque::new();
        queue.push_back(root.get_id());
        visited.insert(root.get_id());

        let mut nodes_to_include = vec![root.clone()];

        while let Some(current_id) = queue.pop_front() {
            let current_node = lookup.get(&current_id).ok_or_else(|| {
                FlagError::DependencyNotFound(T::dependency_type(), current_id.into())
            })?;

            for dep in current_node.extract_dependencies()? {
                // Strict: fail if dependency is not present in pool
                let dep_node = lookup.get(&dep).ok_or_else(|| {
                    FlagError::DependencyNotFound(T::dependency_type(), dep.into())
                })?;

                if visited.insert(dep) {
                    nodes_to_include.push(dep_node.clone());
                    queue.push_back(dep);
                }
            }
        }

        let (graph, errors) = Self::from_nodes(&nodes_to_include)?;

        // If there are any errors (missing dependencies or cycles), fail
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

    /// Builds a full multi-root dependency graph from the provided set of nodes.
    /// Returns a tuple of the graph and a vector of errors.
    /// The errors are returned in the order they were encountered.
    /// The graph is returned even if there are errors.
    /// - Cycles are detected and removed from the graph.
    /// - Missing dependencies are detected and removed from the graph.
    /// - A partial-graph is returned even if there are errors.
    #[allow(clippy::type_complexity)]
    pub fn from_nodes(nodes: &[T]) -> Result<(Self, Vec<GraphError<T::Id>>), T::Error> {
        let mut graph = DiGraph::new();
        let mut id_map = HashMap::with_capacity(nodes.len());
        let mut errors = Vec::new();
        let mut nodes_with_missing_deps = Vec::new();

        // Insert all nodes first
        for node in nodes {
            let idx = graph.add_node(node.clone());
            id_map.insert(node.get_id(), idx);
        }

        // Insert edges and track nodes with missing dependencies
        for node in nodes {
            let source_idx = id_map[&node.get_id()];
            for dep_id in node.extract_dependencies()? {
                if let Some(target_idx) = id_map.get(&dep_id) {
                    graph.add_edge(source_idx, *target_idx, ());
                } else {
                    errors.push(GraphError::MissingDependency(dep_id));
                    nodes_with_missing_deps.push(source_idx);
                }
            }
        }

        // Remove all nodes with missing dependencies and their dependents
        nodes_with_missing_deps.sort_by(|a, b| b.cmp(a));
        for node_idx in nodes_with_missing_deps {
            Self::remove_node_and_dependents_from_graph(&mut graph, node_idx);
        }

        // Remove all cycles from the graph
        Self::remove_all_cycles(&mut graph, &mut errors);

        Ok((Self { graph }, errors))
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
    ///     A → B means "A depends on B" (A requires B to be evaluated first)
    /// - Therefore:
    ///     - Outgoing edges = dependencies
    ///     - Incoming edges = dependents (nodes that require this node)
    ///
    /// The algorithm works by repeatedly finding all nodes that have no remaining dependencies (out-degree == 0),
    /// evaluating them as one stage, and then decrementing the remaining dependencies of their dependents.
    pub fn evaluation_stages(&self) -> Result<Vec<Vec<&T>>, T::Error> {
        let mut out_degree = self.build_evaluation_maps()?;
        Self::compute_stages(&self.graph, &mut out_degree)
    }

    fn build_evaluation_maps(&self) -> Result<HashMap<NodeIndex, usize>, T::Error> {
        use petgraph::Direction::Outgoing;
        let node_count = self.graph.node_count();
        let mut out_degree: HashMap<NodeIndex, usize> = HashMap::with_capacity(node_count);
        for node_idx in self.graph.node_indices() {
            let deg = self.graph.edges_directed(node_idx, Outgoing).count();
            out_degree.insert(node_idx, deg);
        }
        Ok(out_degree)
    }

    fn compute_stages<'a>(
        graph: &'a DiGraph<T, ()>,
        out_degree: &mut HashMap<NodeIndex, usize>,
    ) -> Result<Vec<Vec<&'a T>>, T::Error> {
        use petgraph::Direction::Incoming;
        let node_count = graph.node_count();
        let mut stages = Vec::with_capacity(node_count);
        while !out_degree.is_empty() {
            let mut current_stage = Vec::new();
            for (&node_idx, &deg) in out_degree.iter() {
                if deg == 0 {
                    current_stage.push(node_idx);
                }
            }
            if current_stage.is_empty() {
                return Err(FlagError::DependencyCycle(T::dependency_type(), -1).into());
            }
            let stage_items: Vec<&'a T> = current_stage.iter().map(|idx| &graph[*idx]).collect();
            stages.push(stage_items);
            for node_idx in &current_stage {
                for parent in graph.neighbors_directed(*node_idx, Incoming) {
                    if let Some(deg) = out_degree.get_mut(&parent) {
                        *deg -= 1;
                    }
                }
                out_degree.remove(node_idx);
            }
        }
        Ok(stages)
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

/// Builds a dependency graph for flag evaluation.
/// Returns None only if there were fatal errors during graph construction.
/// Partial errors (cycles, missing dependencies) are returned in the errors vector
/// and the graph contains only the valid nodes.
pub fn build_dependency_graph(
    feature_flags: &crate::flags::flag_models::FeatureFlagList,
    team_id: common_types::TeamId,
) -> Option<(DependencyGraph<FeatureFlag>, Vec<GraphError<i32>>)> {
    // Build the global dependency graph once, handling partial errors gracefully
    let (global_graph, errors) = match DependencyGraph::from_nodes(&feature_flags.flags) {
        Ok((graph, graph_errors)) => (graph, graph_errors),
        Err(e) => {
            log_dependency_graph_operation_error("build global dependency graph", &e, team_id);
            return None; // Only return None for fatal errors
        }
    };

    // Log any dependency errors but continue with the valid graph
    if !errors.is_empty() {
        log_dependency_graph_construction_errors(&errors, team_id);
    }

    Some((global_graph, errors))
}

/// Filters a dependency graph to include only the requested flags and their dependencies.
/// Returns None if:
/// - There were errors during filtering
/// - The global_graph's internal state is corrupted
pub fn filter_graph_by_keys(
    global_graph: &DependencyGraph<FeatureFlag>,
    requested_keys: &[String],
) -> Option<DependencyGraph<FeatureFlag>> {
    let mut nodes_to_include = HashSet::new();

    // Build an index from flag keys to node indices for O(1) lookups
    let key_to_node: HashMap<&str, petgraph::graph::NodeIndex> = global_graph
        .graph
        .node_indices()
        .map(|idx| (global_graph.graph[idx].key.as_str(), idx))
        .collect();

    // For each requested flag, traverse the global graph to collect dependencies
    for key in requested_keys {
        // Find the flag in the global graph using the index
        let node_idx = key_to_node.get(key.as_str());

        if let Some(&start_idx) = node_idx {
            // Use BFS to collect all reachable nodes (dependencies) from this flag
            let mut visited = HashSet::new();
            let mut queue = std::collections::VecDeque::new();
            queue.push_back(start_idx);
            visited.insert(start_idx);

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
            // Log warning for missing flag key
            warn!("Requested flag key not found: {}", key);
            inc(
                FLAG_EVALUATION_ERROR_COUNTER,
                &[(
                    "reason".to_string(),
                    "missing_requested_flag_key".to_string(),
                )],
                1,
            );
        }
    }

    // Create a new graph with only the filtered nodes
    let mut filtered_graph = DiGraph::new();
    let mut node_mapping = HashMap::new();

    // Add all the nodes we want to include
    for &node_idx in &nodes_to_include {
        let flag = global_graph.graph[node_idx].clone();
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

    Some(DependencyGraph {
        graph: filtered_graph,
    })
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
    inc(
        FLAG_EVALUATION_ERROR_COUNTER,
        &[
            ("reason".to_string(), "dependency_graph_error".to_string()),
            ("team_id".to_string(), team_id.to_string()),
        ],
        1,
    );
    tracing::error!(
        "There were errors building the feature flag dependency graph for team {}. Will attempt to evaluate the rest of the flags: {:?}",
        team_id, errors
    );
}

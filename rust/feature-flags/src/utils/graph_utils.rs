use std::collections::{HashMap, HashSet, VecDeque};

use petgraph::{algo::toposort, graph::DiGraph};

use crate::api::errors::FlagError;

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
        f.write_str(&format!("{:?}", self).to_lowercase())
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
    /// Creates a new DependencyGraph from a list of items, starting from an initial item.
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

        Self::build_from_nodes(&nodes_to_include)
    }

    /// Builds a full dependency graph from the provided set of nodes.
    /// Strictly validates cycles and self-referential edges.
    /// Supports multiple roots and independent subgraphs and independent nodes.
    pub fn build_from_nodes(nodes: &[T]) -> Result<Self, T::Error> {
        let mut graph = DiGraph::new();
        let mut id_map = HashMap::new();

        // Insert all nodes first
        for node in nodes {
            let idx = graph.add_node(node.clone());
            id_map.insert(node.get_id(), idx);
        }

        // Insert edges (strict: only between known nodes)
        for node in nodes {
            let source_idx = id_map[&node.get_id()];
            for dep_id in node.extract_dependencies()? {
                if let Some(target_idx) = id_map.get(&dep_id) {
                    graph.add_edge(source_idx, *target_idx, ());
                }
            }
        }

        // Validate cycles after full wiring.
        // Use toposort to detect cycles because it gives us the Id of the node that causes the cycle.
        if let Err(e) = toposort(&graph, None) {
            let cycle_start_node = e.node_id();
            let cycle_id = graph[cycle_start_node].get_id().into();
            return Err(FlagError::DependencyCycle(T::dependency_type(), cycle_id).into());
        }

        Ok(Self { graph })
    }

    /// Traverses the graph in reverse topological order (dependencies first)
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
        use petgraph::Direction::{Incoming, Outgoing};

        // how many dependencies each node has remaining
        let mut out_degree = HashMap::new();
        // maps NodeIndex → &T for easy lookup later
        let mut node_map = HashMap::new();

        // Initialize the out-degree and node_map
        for node_idx in self.graph.node_indices() {
            let node = &self.graph[node_idx];
            node_map.insert(node_idx, node);
            let deg = self.graph.edges_directed(node_idx, Outgoing).count();
            out_degree.insert(node_idx, deg);
        }

        let mut stages = Vec::new();

        // We'll add nodes to stages as we find them.
        // We'll remove nodes from the out_degree map as we process them.
        // We'll stop when the out_degree map is empty.
        while !out_degree.is_empty() {
            let mut current_stage = Vec::new();

            // Find all nodes whose dependencies have been fully satisfied (out-degree == 0)
            for (&node_idx, &deg) in out_degree.iter() {
                if deg == 0 {
                    current_stage.push(node_idx);
                }
            }

            if current_stage.is_empty() {
                // This indicates a cycle — should not occur if graph is properly validated during build (which we do!)
                return Err(FlagError::DependencyCycle(T::dependency_type(), 0).into());
            }

            // Collect references to items in this stage
            let stage_items: Vec<&T> = current_stage.iter().map(|idx| node_map[idx]).collect();
            stages.push(stage_items);

            // After processing current stage, decrement out-degree (dependency count) of parents (dependents)
            for node_idx in &current_stage {
                for parent in self.graph.neighbors_directed(*node_idx, Incoming) {
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
}

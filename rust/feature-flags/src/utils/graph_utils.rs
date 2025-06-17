use std::collections::{hash_map::Entry, HashMap, HashSet, VecDeque};

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

/// Maps dependency IDs to their corresponding node indices in the graph
type NodeMap<T> = HashMap<<T as DependencyProvider>::Id, petgraph::graph::NodeIndex>;

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
    pub fn new(initial_item: T, items: &[T]) -> Result<Self, T::Error> {
        let mut graph = DiGraph::new();
        let mut node_map = NodeMap::<T>::new();
        let mut queue = VecDeque::new();

        let initial_id = initial_item.get_id();
        let initial_node = graph.add_node(initial_item);
        node_map.insert(initial_id, initial_node);
        queue.push_back(initial_id);

        while let Some(item_id) = queue.pop_front() {
            let current_node = node_map[&item_id];
            let item = &graph[current_node];
            let dependencies = item.extract_dependencies()?;

            for dep_id in dependencies {
                if dep_id == item_id {
                    return Err(
                        FlagError::DependencyCycle(T::dependency_type(), dep_id.into()).into(),
                    );
                }

                let dep_node = if !node_map.contains_key(&dep_id) {
                    Self::find_and_add_node(items, dep_id, &mut graph, &mut node_map, &mut queue)?
                } else {
                    node_map[&dep_id]
                };

                // Safe to add edge without checking: BFS processes each node exactly once,
                // and HashSet ensures unique dependencies per node
                graph.add_edge(current_node, dep_node, ());
            }
        }

        match toposort(&graph, None) {
            Ok(_) => Ok(Self { graph }),
            Err(cycle) => Err(FlagError::DependencyCycle(
                T::dependency_type(),
                graph[cycle.node_id()].get_id().into(),
            )
            .into()),
        }
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

    /// Helper to get a node's ID as an i64
    fn get_node_id(&self, index: petgraph::graph::NodeIndex) -> i64 {
        self.graph[index].get_id().into()
    }

    fn find_and_add_node(
        items: &[T],
        item_id: T::Id,
        graph: &mut DiGraph<T, ()>,
        node_map: &mut NodeMap<T>,
        queue: &mut VecDeque<T::Id>,
    ) -> Result<petgraph::graph::NodeIndex, T::Error> {
        let item = items
            .iter()
            .find(|item| item.get_id() == item_id)
            .ok_or_else(|| FlagError::DependencyNotFound(T::dependency_type(), item_id.into()))?;

        let node = match node_map.entry(item_id) {
            Entry::Occupied(entry) => *entry.get(),
            Entry::Vacant(entry) => {
                let node = graph.add_node(item.clone());
                entry.insert(node);
                queue.push_back(item_id);
                node
            }
        };

        Ok(node)
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

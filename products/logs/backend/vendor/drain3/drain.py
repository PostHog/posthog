# Vendored from drain3 0.9.11 — https://github.com/IBM/Drain3
# Local changes: import made relative; ruff-formatted/fixed; ty annotation fixes.
#
# MIT License
#
# Copyright (c) 2020-2022 International Business Machines
# and the Drain3 project contributors.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# ruff: noqa
# mypy: ignore-errors
# SPDX-License-Identifier: MIT
# This file implements the Drain algorithm for log parsing.
# Based on https://github.com/logpai/logparser/blob/master/logparser/Drain/Drain.py by LogPAI team

from collections.abc import Sequence

from cachetools import Cache, LRUCache

from .simple_profiler import NullProfiler, Profiler


class LogCluster:
    __slots__ = ["log_template_tokens", "cluster_id", "size"]

    def __init__(self, log_template_tokens: list, cluster_id: int):
        self.log_template_tokens = tuple(log_template_tokens)
        self.cluster_id = cluster_id
        self.size = 1

    def get_template(self):
        return " ".join(self.log_template_tokens)

    def __str__(self):
        return f"ID={str(self.cluster_id).ljust(5)} : size={str(self.size).ljust(10)}: {self.get_template()}"


class LogClusterCache(LRUCache):
    """
    Least Recently Used (LRU) cache which allows callers to conditionally skip
    cache eviction algorithm when accessing elements.
    """

    def __missing__(self, key):
        return None

    def get(self, key):
        """
        Returns the value of the item with the specified key without updating
        the cache eviction algorithm.
        """
        return Cache.__getitem__(self, key)


class Node:
    __slots__ = ["key_to_child_node", "cluster_ids"]

    def __init__(self):
        self.key_to_child_node: dict[str, Node] = {}
        self.cluster_ids: list[int] = []


class Drain:
    def __init__(
        self,
        depth=4,
        sim_th=0.4,
        max_children=100,
        max_clusters=None,
        extra_delimiters=(),
        profiler: Profiler = NullProfiler(),
        param_str="<*>",
        parametrize_numeric_tokens=True,
    ):
        """
        Create a new Drain instance.

        :param depth: max depth levels of log clusters. Minimum is 2.
            For example, for depth==4, Root is considered depth level 1.
            Token count is considered depth level 2.
            First log token is considered depth level 3.
            Log clusters below first token node are considered depth level 4.
        :param sim_th: similarity threshold - if percentage of similar tokens for a log message is below this
            number, a new log cluster will be created.
        :param max_children: max number of children of an internal node
        :param max_clusters: max number of tracked clusters (unlimited by default).
            When this number is reached, model starts replacing old clusters
            with a new ones according to the LRU policy.
        :param extra_delimiters: delimiters to apply when splitting log message into words (in addition to whitespace).
        :param parametrize_numeric_tokens: whether to treat tokens that contains at least one digit
            as template parameters.
        """
        if depth < 3:
            raise ValueError("depth argument must be at least 3")

        self.log_cluster_depth = depth
        self.max_node_depth = depth - 2  # max depth of a prefix tree node, starting from zero
        self.sim_th = sim_th
        self.max_children = max_children
        self.root_node = Node()
        self.profiler = profiler
        self.extra_delimiters = extra_delimiters
        self.max_clusters = max_clusters
        self.param_str = param_str
        self.parametrize_numeric_tokens = parametrize_numeric_tokens

        # key: int, value: LogCluster
        self.id_to_cluster = {} if max_clusters is None else LogClusterCache(maxsize=max_clusters)
        self.clusters_counter = 0

    @property
    def clusters(self):
        return self.id_to_cluster.values()

    @staticmethod
    def has_numbers(s):
        return any(char.isdigit() for char in s)

    def tree_search(self, root_node: Node, tokens: list, sim_th: float, include_params: bool):

        # at first level, children are grouped by token (word) count
        token_count = len(tokens)
        cur_node = root_node.key_to_child_node.get(str(token_count))

        # no template with same token count yet
        if cur_node is None:
            return None

        # handle case of empty log string - return the single cluster in that group
        if token_count == 0:
            return self.id_to_cluster.get(cur_node.cluster_ids[0])

        # find the leaf node for this log - a path of nodes matching the first N tokens (N=tree depth)
        cur_node_depth = 1
        for token in tokens:
            # at max depth
            if cur_node_depth >= self.max_node_depth:
                break

            # this is last token
            if cur_node_depth == token_count:
                break

            key_to_child_node = cur_node.key_to_child_node
            cur_node = key_to_child_node.get(token)
            if cur_node is None:  # no exact next token exist, try wildcard node
                cur_node = key_to_child_node.get(self.param_str)
            if cur_node is None:  # no wildcard node exist
                return None

            cur_node_depth += 1

        # get best match among all clusters with same prefix, or None if no match is above sim_th
        cluster = self.fast_match(cur_node.cluster_ids, tokens, sim_th, include_params)
        return cluster

    def add_seq_to_prefix_tree(self, root_node, cluster: LogCluster):
        token_count = len(cluster.log_template_tokens)
        token_count_str = str(token_count)
        if token_count_str not in root_node.key_to_child_node:
            first_layer_node = Node()
            root_node.key_to_child_node[token_count_str] = first_layer_node
        else:
            first_layer_node = root_node.key_to_child_node[token_count_str]

        cur_node = first_layer_node

        # handle case of empty log string
        if token_count == 0:
            cur_node.cluster_ids = [cluster.cluster_id]
            return

        current_depth = 1
        for token in cluster.log_template_tokens:
            # if at max depth or this is last token in template - add current log cluster to the leaf node
            if current_depth >= self.max_node_depth or current_depth >= token_count:
                # clean up stale clusters before adding a new one.
                new_cluster_ids = []
                for cluster_id in cur_node.cluster_ids:
                    if cluster_id in self.id_to_cluster:
                        new_cluster_ids.append(cluster_id)
                new_cluster_ids.append(cluster.cluster_id)
                cur_node.cluster_ids = new_cluster_ids
                break

            # if token not matched in this layer of existing tree.
            if token not in cur_node.key_to_child_node:
                if self.parametrize_numeric_tokens and self.has_numbers(token):
                    if self.param_str not in cur_node.key_to_child_node:
                        new_node = Node()
                        cur_node.key_to_child_node[self.param_str] = new_node
                        cur_node = new_node
                    else:
                        cur_node = cur_node.key_to_child_node[self.param_str]

                else:
                    if self.param_str in cur_node.key_to_child_node:
                        if len(cur_node.key_to_child_node) < self.max_children:
                            new_node = Node()
                            cur_node.key_to_child_node[token] = new_node
                            cur_node = new_node
                        else:
                            cur_node = cur_node.key_to_child_node[self.param_str]
                    else:
                        if len(cur_node.key_to_child_node) + 1 < self.max_children:
                            new_node = Node()
                            cur_node.key_to_child_node[token] = new_node
                            cur_node = new_node
                        elif len(cur_node.key_to_child_node) + 1 == self.max_children:
                            new_node = Node()
                            cur_node.key_to_child_node[self.param_str] = new_node
                            cur_node = new_node
                        else:
                            cur_node = cur_node.key_to_child_node[self.param_str]

            # if the token is matched
            else:
                cur_node = cur_node.key_to_child_node[token]

            current_depth += 1

    # seq1 is a template, seq2 is the log to match
    def get_seq_distance(self, seq1, seq2, include_params: bool):
        assert len(seq1) == len(seq2)

        # sequences are empty - full match
        if len(seq1) == 0:
            return 1.0, 0

        sim_tokens = 0
        param_count = 0

        for token1, token2 in zip(seq1, seq2):
            if token1 == self.param_str:
                param_count += 1
                continue
            if token1 == token2:
                sim_tokens += 1

        if include_params:
            sim_tokens += param_count

        ret_val = float(sim_tokens) / len(seq1)

        return ret_val, param_count

    def fast_match(self, cluster_ids: Sequence, tokens: list, sim_th: float, include_params: bool):
        """
        Find the best match for a log message (represented as tokens) versus a list of clusters
        :param cluster_ids: List of clusters to match against (represented by their IDs)
        :param tokens: the log message, separated to tokens.
        :param sim_th: minimum required similarity threshold (None will be returned in no clusters reached it)
        :param include_params: consider tokens matched to wildcard parameters in similarity threshold.
        :return: Best match cluster or None
        """
        match_cluster = None

        max_sim = -1
        max_param_count = -1
        max_cluster = None

        for cluster_id in cluster_ids:
            # Try to retrieve cluster from cache with bypassing eviction
            # algorithm as we are only testing candidates for a match.
            cluster = self.id_to_cluster.get(cluster_id)
            if cluster is None:
                continue
            cur_sim, param_count = self.get_seq_distance(cluster.log_template_tokens, tokens, include_params)
            if cur_sim > max_sim or (cur_sim == max_sim and param_count > max_param_count):
                max_sim = cur_sim
                max_param_count = param_count
                max_cluster = cluster

        if max_sim >= sim_th:
            match_cluster = max_cluster

        return match_cluster

    def create_template(self, seq1, seq2):
        assert len(seq1) == len(seq2)
        ret_val = list(seq2)

        for i, (token1, token2) in enumerate(zip(seq1, seq2)):
            if token1 != token2:
                ret_val[i] = self.param_str

        return ret_val

    def print_tree(self, file=None, max_clusters=5):
        self.print_node("root", self.root_node, 0, file, max_clusters)

    def print_node(self, token, node, depth, file, max_clusters):
        out_str = "\t" * depth

        if depth == 0:
            out_str += f"<{token}>"
        elif depth == 1:
            out_str += f"<L={token}>"
        else:
            out_str += f'"{token}"'

        if len(node.cluster_ids) > 0:
            out_str += f" (cluster_count={len(node.cluster_ids)})"

        print(out_str, file=file)

        for token, child in node.key_to_child_node.items():
            self.print_node(token, child, depth + 1, file, max_clusters)

        for cid in node.cluster_ids[:max_clusters]:
            cluster = self.id_to_cluster[cid]
            out_str = "\t" * (depth + 1) + str(cluster)
            print(out_str, file=file)

    def get_content_as_tokens(self, content):
        content = content.strip()
        for delimiter in self.extra_delimiters:
            content = content.replace(delimiter, " ")
        content_tokens = content.split()
        return content_tokens

    def add_log_message(self, content: str):
        content_tokens = self.get_content_as_tokens(content)

        if self.profiler:
            self.profiler.start_section("tree_search")
        match_cluster = self.tree_search(self.root_node, content_tokens, self.sim_th, False)
        if self.profiler:
            self.profiler.end_section()

        # Match no existing log cluster
        if match_cluster is None:
            if self.profiler:
                self.profiler.start_section("create_cluster")
            self.clusters_counter += 1
            cluster_id = self.clusters_counter
            match_cluster = LogCluster(content_tokens, cluster_id)
            self.id_to_cluster[cluster_id] = match_cluster
            self.add_seq_to_prefix_tree(self.root_node, match_cluster)
            update_type = "cluster_created"

        # Add the new log message to the existing cluster
        else:
            if self.profiler:
                self.profiler.start_section("cluster_exist")
            new_template_tokens = self.create_template(content_tokens, match_cluster.log_template_tokens)
            if tuple(new_template_tokens) == match_cluster.log_template_tokens:
                update_type = "none"
            else:
                match_cluster.log_template_tokens = tuple(new_template_tokens)
                update_type = "cluster_template_changed"
            match_cluster.size += 1
            # Touch cluster to update its state in the cache.
            # noinspection PyStatementEffect
            self.id_to_cluster[match_cluster.cluster_id]

        if self.profiler:
            self.profiler.end_section()

        return match_cluster, update_type

    def get_clusters_ids_for_seq_len(self, seq_len: int):
        """
        Return all clusters with the specified count of tokens
        """

        def append_clusters_recursive(node: Node, id_list_to_fill: list):
            id_list_to_fill.extend(node.cluster_ids)
            for child_node in node.key_to_child_node.values():
                append_clusters_recursive(child_node, id_list_to_fill)

        cur_node = self.root_node.key_to_child_node.get(str(seq_len))

        # no template with same token count
        if cur_node is None:
            return []

        target = []
        append_clusters_recursive(cur_node, target)
        return target

    def match(self, content: str, full_search_strategy="never"):
        """
        Match log message against an already existing cluster.
        Match shall be perfect (sim_th=1.0).
        New cluster will not be created as a result of this call, nor any cluster modifications.

        :param content: log message to match
        :param full_search_strategy: when to perform full cluster search.
            (1) "never" is the fastest, will always perform a tree search [O(log(n)] but might produce
            false negatives (wrong mismatches) on some edge cases;
            (2) "fallback" will perform a linear search [O(n)] among all clusters with the same token count, but only in
            case tree search found no match.
            It should not have false negatives, however tree-search may find a non-optimal match with
            more wildcard parameters than necessary;
            (3) "always" is the slowest. It will select the best match among all known clusters, by always evaluating
            all clusters with the same token count, and selecting the cluster with perfect all token match and least
            count of wildcard matches.
        :return: Matched cluster or None if no match found.
        """

        assert full_search_strategy in ["always", "never", "fallback"]

        required_sim_th = 1.0
        content_tokens = self.get_content_as_tokens(content)

        # consider for future improvement:
        # It is possible to implement a recursive tree_search (first try exact token match and fallback to
        # wildcard match). This will be both accurate and more efficient than the linear full search
        # also fast match can be optimized when exact match is required by early
        # quitting on less than exact cluster matches.
        def full_search():
            all_ids = self.get_clusters_ids_for_seq_len(len(content_tokens))
            cluster = self.fast_match(all_ids, content_tokens, required_sim_th, include_params=True)
            return cluster

        if full_search_strategy == "always":
            return full_search()

        match_cluster = self.tree_search(self.root_node, content_tokens, required_sim_th, include_params=True)
        if match_cluster is not None:
            return match_cluster

        if full_search_strategy == "never":
            return None

        return full_search()

    def get_total_cluster_size(self):
        size = 0
        for c in self.id_to_cluster.values():
            size += c.size
        return size

# Vendored training builders

This directory contains only the local Python closure required by the orchestrated pair, GroupJoin, split-gate, and shuffler training stages. It is vendored so the project never imports another checkout.

The direct entry points are:

- `train_pair.py`, `export_models.py`, and `train_gate.py`
- `groupjoin_features.py`, `train_groupjoin.py`, `train_groupjoin_neural.py`, `finalize_groupjoin_stack.py`, and `export_groupjoin_onnx.py`
- `build_member_alignment_edges.py`, `extract_member_pair_features.py`, `score_member_alignment_graphs.py`, `train_member_compatibility.py`, `train_member_report_gate.py`, `train_member_selector.py`, and `train_member_operation_risk.py`
- `train_integrated_report_shuffler.py` and `export_integrated_report_shuffler.py`

The remaining files are their exact transitive local import closure. Historical feature-contract strings are retained because the Rust kernels validate them.

One dependency adaptation is intentional: GroupJoin fold assignment no longer discovers report groups through module globals or historical data files. `train_groupjoin.py`, `train_groupjoin_neural.py`, and `finalize_groupjoin_stack.py` require `--document-groups`, and the orchestrator passes the map emitted for the newly dealt train territory.

Files named `*_oof` are model-local fold products. Downstream models can consume features from upstream models fitted on overlapping train operations, so these are not end-to-end out-of-fold predictions and their local metrics are not unbiased calibration estimates. The orchestrator relies on territory-held-out validation A and the one-shot frozen validation B run for end-to-end conclusions.

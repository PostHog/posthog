# Serde Elements

A Python extension for deserialization of PostHog HTML elements (as represented by the [`Element` model](../posthog/models/element/element.py))

# Build & Install
Build with `maturin`:
```sh
maturin build --release
```

Install Python wheel:
```sh
pip install target/wheels/serde_elements_chain-0.1.0-cp311-cp311-manylinux_2_34_x86_64.whl
```

# Usage
```Python
from serde_elements import deserialize

elements_chain = ...
d = deserialize(elements_chain)
```

from products.signals.backend.enums import SignalSourceProduct

# pinned: what a scout's config records as its owner. Signals stores it as `(source_product,
# source_id)`, where source_id is the scanner's id, and that pair is what ties a scout back to the
# scanner it watches — for finding them, for authorizing report reads, and for cleanup.
SCOUT_SOURCE_PRODUCT = SignalSourceProduct.REPLAY_VISION.value

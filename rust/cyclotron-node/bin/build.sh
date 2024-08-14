#!/bin/bash
set -e

npm install

# This generates an "index.node", which
# you then `require()` the directory of to load.
npm run build

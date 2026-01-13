#!/bin/bash

# Script to remove formatResponse wrapper from tool files (handles multi-line)
# Changes: return {
#              content: [{ type: 'text', text: formatResponse(X) }],
#          }
# To: return X

count=0

for file in $(find . -name "*.ts" -type f); do
    # Check if file contains formatResponse
    if grep -q "formatResponse" "$file"; then
        # Use perl to handle multi-line pattern
        perl -0777 -i -pe 's/return\s*\{\s*content:\s*\[\s*\{\s*type:\s*['\''"]text['\''"]\s*,\s*text:\s*formatResponse\(((?:[^()]+|\((?:[^()]+|\([^()]*\))*\))*)\)\s*\}\s*\]\s*,?\s*\}/return $1/gs' "$file"

        if ! grep -q "formatResponse" "$file"; then
            ((count++))
            echo "Updated: $file"
        fi
    fi
done

echo ""
echo "Total files updated: $count"

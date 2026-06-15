#!/bin/bash

# Script to remove formatResponse wrapper from tool files
# Changes: return { content: [{ type: 'text', text: formatResponse(X) }] }
# To: return X

count=0

for file in $(find . -name "*.ts" -type f); do
    # Check if file contains the pattern we want to change
    if grep -q "formatResponse" "$file"; then
        # Remove the import line
        sed -i.bak "/import.*formatResponse.*from/d" "$file"

        # Replace the return pattern - handles single line cases
        perl -i -pe 's/return\s+\{\s*content:\s*\[\s*\{\s*type:\s*['\''"]text['\''"]\s*,\s*text:\s*formatResponse\((.*?)\)\s*\}\s*\]\s*\}/return $1/g' "$file"

        # Remove .bak file if no changes were made
        if diff "$file" "$file.bak" > /dev/null 2>&1; then
            rm "$file.bak"
        else
            rm "$file.bak"
            ((count++))
            echo "Updated: $file"
        fi
    fi
done

echo ""
echo "Total files updated: $count"

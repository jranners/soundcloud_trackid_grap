import re

with open('app/templates/index.html', 'r') as f:
    content = f.read()

content = content.replace(
    '<label for="set-search-input" class="form-label sr-only">SETS FILTERN</label>',
    ''
)

content = content.replace(
    '<label for="set-search-input" class="form-label sr-only" style="display:none;">SETS FILTERN</label>',
    '<label for="set-search-input" class="form-label sr-only">SETS FILTERN</label>'
)

with open('app/templates/index.html', 'w') as f:
    f.write(content)

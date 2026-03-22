import re

with open('app/templates/index.html', 'r') as f:
    content = f.read()

# 1. Label text to "SOUNDCLOUD URL HIER EINFÜGEN" (uppercase is handled by CSS, but we can uppercase it here too to be safe)
content = re.sub(r'<label class="form-label" for="url-input">SoundCloud URL</label>', '<label class="form-label" for="url-input">SOUNDCLOUD URL HIER EINFÜGEN</label>', content)

# 2. Analyze button text to "Analysieren", and aria-busy="false"
content = re.sub(r'<button id="analyze-btn" class="btn btn-primary">([\s\S]*?)Analyze\s*</button>', r'<button id="analyze-btn" class="btn btn-primary" aria-busy="false">\1Analysieren\n        </button>', content)

# 3. Add label for set-search-input
search_input_html = r'''<input
          id="set-search-input"'''

replacement = r'''<label for="set-search-input" class="form-label sr-only">SETS FILTERN</label>
        <input
          id="set-search-input"'''

content = content.replace(search_input_html, replacement)

# write back
with open('app/templates/index.html', 'w') as f:
    f.write(content)

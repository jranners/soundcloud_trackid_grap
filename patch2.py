import re

with open('app/templates/index.html', 'r') as f:
    content = f.read()

content = content.replace(
    '<label class="form-label" for="url-input">SOUNDCLOUD URL HIER EINFÜGEN</label>',
    '<label class="form-label" for="url-input">SOUNDCLOUD URL HIER EINFÜGEN</label>'
)

content = content.replace(
    '<label class="form-label" for="url-input">SoundCloud URL</label>',
    '<label class="form-label" for="url-input">SOUNDCLOUD URL HIER EINFÜGEN</label>'
)

content = re.sub(
    r'<button id="analyze-btn" class="btn btn-primary">([\s\S]*?)\s*Analyze\s*</button>',
    r'<button id="analyze-btn" class="btn btn-primary" aria-busy="false">\1Analysieren\n        </button>',
    content
)

search_input_html = '''<input
          id="set-search-input"'''

replacement = '''<label for="set-search-input" class="form-label sr-only" style="display:none;">SETS FILTERN</label>
        <input
          id="set-search-input"'''

content = content.replace(search_input_html, replacement)

with open('app/templates/index.html', 'w') as f:
    f.write(content)

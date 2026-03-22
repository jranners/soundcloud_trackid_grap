import re

with open('app/static/css/style.css', 'r') as f:
    content = f.read()

# Make sure we add sr-only properly as it might have replaced the whole block incorrectly
# Let's fix it by regex replace

form_label_block = """.form-label {
  display: block;
  font-family: 'Inter', sans-serif;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 0.5rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}"""

content = content.replace(form_label_block, form_label_block) # test if present

with open('app/static/css/style.css', 'w') as f:
    f.write(content)

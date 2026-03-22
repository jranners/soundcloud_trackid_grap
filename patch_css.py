import re

with open('app/static/css/style.css', 'r') as f:
    content = f.read()

# Add new CSS variables
vars_insert = """  --sc-orange: #ff5500;
  --sc-orange-hover: #ff7733;
  --sc-orange-dim: rgba(255, 85, 0, 0.15);
  --primary: #ff8342;
  --primary-container: #fe6b00;
  --surface-container-low: #131313;
  --surface-container-high: #201f1f;"""

content = re.sub(r'  --sc-orange: #ff5500;[\s\S]*?--sc-orange-dim: rgba\(255, 85, 0, 0\.15\);', vars_insert, content, count=1)

# Update .form-label
form_label_new = """.form-label {
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
content = re.sub(r'\.form-label\s*{[\s\S]*?}', form_label_new, content, count=1)

# Update inputs to remove 1px border and use new background/focus logic
url_input_new = """.url-input {
  flex: 1;
  background: var(--surface-container-low);
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: 0.95rem;
  padding: 0.75rem 1rem;
  outline: none;
  transition: background var(--transition), box-shadow var(--transition);
}

.url-input::placeholder {
  color: var(--text-muted);
}

.url-input:focus {
  background: var(--surface-container-high);
  box-shadow: inset 0 0 0 1px rgba(255, 131, 66, 0.3);
}"""

content = re.sub(r'\.url-input\s*{[\s\S]*?}\s*\.url-input::placeholder\s*{[\s\S]*?}\s*\.url-input:focus\s*{[\s\S]*?}', url_input_new, content, count=1)


# Update .btn-primary
btn_primary_new = """.btn-primary {
  background: linear-gradient(135deg, var(--primary), var(--primary-container));
  color: #fff;
  position: relative;
  overflow: hidden;
  z-index: 1;
}

.btn-primary.is-loading {
  pointer-events: none;
  box-shadow: 0 0 40px rgba(255, 131, 66, 0.08);
}

.btn-primary.is-loading::before {
  content: '';
  position: absolute;
  top: 0; left: 0; width: 100%; height: 100%;
  background: linear-gradient(135deg, var(--primary-container), var(--primary));
  z-index: -1;
  animation: pulse-gradient 1.5s infinite alternate ease-in-out;
}

@keyframes pulse-gradient {
  0% {
    opacity: 0;
  }
  100% {
    opacity: 1;
  }
}"""

content = re.sub(r'\.btn-primary\s*{[\s\S]*?}', btn_primary_new, content, count=1)

# Write back
with open('app/static/css/style.css', 'w') as f:
    f.write(content)

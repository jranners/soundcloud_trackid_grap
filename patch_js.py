import re

with open('app/static/js/app.js', 'r') as f:
    content = f.read()

# Replace starting analysis UI update
start_analysis_old = """  hideError();
  analyzeBtn.disabled = true;"""
start_analysis_new = """  hideError();
  analyzeBtn.disabled = true;
  analyzeBtn.classList.add("is-loading");
  analyzeBtn.setAttribute("aria-busy", "true");"""

content = content.replace(start_analysis_old, start_analysis_new)

# Replace finally block
finally_old = """  } finally {
    analyzeBtn.disabled = false;
  }"""
finally_new = """  } finally {
    analyzeBtn.disabled = false;
    analyzeBtn.classList.remove("is-loading");
    analyzeBtn.setAttribute("aria-busy", "false");
  }"""

content = content.replace(finally_old, finally_new)

with open('app/static/js/app.js', 'w') as f:
    f.write(content)

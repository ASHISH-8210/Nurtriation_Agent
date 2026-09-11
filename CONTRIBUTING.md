# Contributing to NutriMind

Thank you for your interest in contributing! Here is everything you need to get started.

---

## Development Setup

1. **Fork and clone**
   `
   git clone https://github.com/ASHISH-8210/Nurtriation_Agent.git
   cd Nurtriation_Agent/nutrimind
   `

2. **Create a virtual environment**
   `
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   `

3. **Copy and fill environment variables**
   `
   cp .env.example .env
   # Edit .env with your IBM Cloud credentials
   `

4. **Run the MCP tools server locally**
   `
   python tools/nutrimind_tools.py
   `

5. **Run tests**
   `
   python tests/test_conversations.py
   `

---

## Branch Naming

| Type | Pattern | Example |
|---|---|---|
| Feature | eat/<short-desc> | eat/voice-input |
| Bug fix | ix/<short-desc> | ix/allergy-guard-sesame |
| Docs | docs/<short-desc> | docs/update-readme |

---

## Pull Request Checklist

- [ ] All tests pass (python tests/test_conversations.py)
- [ ] No secrets or .env files committed
- [ ] Code follows existing style (PEP 8, type hints where present)
- [ ] New tools are registered in gent/agent.yaml
- [ ] equirements.txt updated if new dependencies added

---

## Reporting Issues

Open an issue with:
- **Clear title** describing the bug or request
- **Steps to reproduce** (for bugs)
- **Expected vs actual behaviour**
- **Python version** and relevant environment details

---

## Code of Conduct

Be respectful and constructive. This project is health-adjacent — accuracy and safety matter.
Never PR changes that weaken the allergy guard or safety escalation logic without clear justification and tests.

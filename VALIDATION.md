# Validation — 2026-10-12

Environment: Ubuntu/Linux, CPython 3.12.3. A new virtual environment was created outside
the original project. Project requirements installed successfully from the package index.
Resolved project dependencies are recorded in requirements.lock.txt (84 distributions).
System Python and the original virtual environment were not changed.

| Check | Result |
| --- | --- |
| pytest | 28 passed; mocked API, extraction retries, invoice rules, report escaping, URL destination checks, synthetic PDF text, RAW Sheets cells and PDF resource blocking |
| API smoke checks | TestClient health and validation/duplicate/invoice/download cases passed; included in pytest count |
| Python compileall | Passed for api.py, shared/, invoice_extraction/, web_research/ and tests/ |
| Import validation | All retained application modules and api imported without credentials |
| pip check | No broken requirements found |
| Dependency audit | No known vulnerabilities found after updating isolated environment pip to a fixed version |
| Docker Compose config | Passed; this validates configuration, not running containers |
| Gitleaks working content | No findings in publishing content |
| Gitleaks committed history | Run after the preparation commit; recorded in final report |
| Frontend build | Not applicable: no frontend package manifest |
| Lint | Not configured in original project |

Three warnings remain: deprecated Google Generative AI SDK, Starlette TestClient's
httpx compatibility warning and a WeasyPrint HarfBuzz-Subset system-library warning. The tests still passed. Initial API testing inside the
restricted sandbox stalled in TestClient threading; it was terminated, and the fresh
environment suite passed with approved execution outside that sandbox.

## NOT RUN

- Live Gemini/Groq extraction or synthesis: needs credentials, model availability and paid calls.
- Live SerpAPI/Tavily searches and Playwright browser integration: external network/browser setup.
- Tesseract OCR against scanned documents: requires installed language packs and synthetic scan fixtures.
- Visual PDF/Arabic typography verification: platform fonts/native libraries and visual review needed.
  The PDF test verifies blocked resource-fetch configuration, not full rendering fidelity.
- Google Sheets and Supabase integration: requires owner-selected stores and write authorization.
- n8n container startup, workflow execution, Drive/Gmail delivery: requires Docker service access,
  credentials, destination configuration and explicit authorization for communications.
- Cross-platform and alternate Python-version compatibility.

Known-advisory results do not establish freedom from unknown vulnerabilities. The
floating n8n container image was not pulled or audited. No secrets were sent to the
vulnerability service; only public package names and versions were queried.

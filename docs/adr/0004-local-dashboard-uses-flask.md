# Local dashboard uses Flask

The dashboard needs browser reload to rediscover saved Captures while preserving the selected Capture Pair, which a generated static HTML file cannot do. Use a small Flask app bound to localhost, with server-rendered HTML, embedded Opportunity List data, and vanilla browser JavaScript. Add Flask as a runtime dependency, expose `uv run dev` and `uv run dashboard` as aliases, and keep the app free of hosted access, frontend build tooling, and dashboard-triggered source capture.

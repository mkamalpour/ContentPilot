# ContentPilot

**[Explore the interactive project presentation](docs/overview.html)** — open locally in your browser; works offline.

Research a topic or public web page, draft an article with a local or hosted model, and keep your writing in a searchable library. WordPress delivery is optional; you can use ContentPilot just to write and save drafts.

## Try it first

Open **Settings** and check your model connection, then use **Studio** to draft from a topic or public URL. Review the saved result in **Library** before configuring schedules or WordPress. The dashboard opens without a model, but drafting needs a working provider.

## What it does

- **Source-grounded drafting:** URL-based articles retain the original excerpt and source URL in the writing prompt.
- **Local or hosted models:** LM Studio chat/completion compatibility with model detection, or explicit Hugging Face chat generation.
- **Editorial workspace:** Responsive Studio, searchable Library, Trends, Automations, Assistant, Activity and Settings views.
- **Durable scheduling:** Interval and one-time jobs survive restarts, run serially, and respect UTC dates and optional time windows.
- **Controlled delivery:** Local saves do not trigger hidden publishing hooks. Send a reviewed draft to WordPress explicitly; optional automatic delivery requires configuration.
- **Bounded operations:** Request timeouts, source download limits, validated redirects, cancellation checks and visible errors.

## Run locally

Use an existing compatible environment. The current offline tests pass in Conda `base` with Python **3.13.5**. The project uses one dependency file.

```powershell
git clone https://github.com/mkamalpour/ContentPilot.git
cd ContentPilot
conda activate base  # Or use your existing compatible environment.
# Install dependencies if they are not already available in your environment.
python -m pip install -r requirements.txt
python main.py
```

On macOS/Linux, activate an existing compatible environment before using the same Python commands.

Open **http://127.0.0.1:8000**. Load a text-generation model in LM Studio and enable its local server before generating. The dashboard starts without a model; generation reports a clear error until one is available. It never substitutes a fabricated article for a provider failure.

Use `python main.py --port 8001` to select another port. Development reload is opt-in: `python main.py --reload`. API reference: `/docs` (requires the configured key when authentication is enabled).

## Configuration

Create an optional `.env` in the project root. Existing environment variables take precedence.

```dotenv
MODEL_PROVIDER=local
LMSTUDIO_API_BASE=http://127.0.0.1:1234/v1
LMSTUDIO_MODEL=
LMSTUDIO_API_KEY=
MODEL_TIMEOUT=120
MAX_TOKENS=1800

CONTENT_AGENT_HOST=127.0.0.1
CONTENT_AGENT_PORT=8000
CONTENTPILOT_API_KEY=
```

Leave `LMSTUDIO_MODEL` empty to detect an available text model. Base URLs with or without `/v1` are accepted. Unsupported chat routes can use the completion route. Provider-specific generation parameters are kept minimal for compatibility, and reasoning wrappers are removed without deleting dates, punctuation or Markdown.

For hosted generation, set `MODEL_PROVIDER=hf`, `HF_TOKEN` and `HF_MODEL` to an available chat model. Requests use the [Hugging Face Inference Providers chat endpoint](https://huggingface.co/docs/inference-providers/en/index). Switching providers is explicit; local mode never silently sends your source material to a cloud model.

The shared API key protects content, generation, scheduling and administrative routes. The launcher requires a key before binding beyond loopback. This is a local operator workspace, not an internet-facing multi-user service with account isolation.

## WordPress

```dotenv
WORDPRESS_API_URL=https://your-site.example/wp-json/wp/v2/posts
WORDPRESS_USERNAME=your_username
WORDPRESS_PASSWORD=your_application_password
WORDPRESS_AUTO_PUBLISH=false
WORDPRESS_DEFAULT_STATUS=draft
```

Use a WordPress application password. Once configured, saved drafts expose explicit **Send to WordPress drafts** and **Publish on WordPress** actions. Repeated delivery of the same saved article updates its recorded WordPress post rather than creating another one. Markdown is converted to sanitized HTML.

Automatic delivery is disabled by default. If you intentionally enable `WORDPRESS_AUTO_PUBLISH=true`, new content is sent using `WORDPRESS_DEFAULT_STATUS` (`draft` by default; set `publish` only for intentional public posting). Delivery failure preserves the local article for review and retry.

## Scheduling and cancellation

Choose either an interval (`HH:MM:SS`, at least five seconds) or specific future dates, with optional start/end bounds. Browser date fields use your local timezone and send UTC timestamps. Naive API datetimes are interpreted as UTC.

Intervals run once their delay has elapsed and are rescheduled from completion. A five-second rest separates automated runs. A single execution lock covers generation, chat, delivery and destructive content operations, so conflicting requests receive a clear busy response.

**Cancel schedules** disables pending jobs and asks any in-flight generation to discard its result before saving. An active HTTP request cannot be interrupted immediately; its configured timeout still applies, and another job cannot overlap it. Completed content is retained. Missed one-time jobs older than a minute expire rather than replaying a backlog. Interrupted running jobs require review and re-enabling after restart.

Schedules are stored in SQLite. Run **one application process/worker**; the serial execution lock is process-local. Advanced test-clock controls are available in Automations and reset to real time on application restart.

## Data and source fetching

`data.db` holds saved content and schedules. `logs/contentpilot.log` uses size-based rotation. Both, along with credentials, virtual environments, caches and editor metadata, are excluded from Git. Existing content receives additive WordPress-tracking columns at first startup; records are retained. `DATABASE_URL` and `CONTENTPILOT_LOG_PATH` can select alternative local storage.

Source downloads accept public HTTP/HTTPS HTML/text pages, check addresses and redirects, and enforce size/time limits. Pages requiring authentication, JavaScript-only rendering or bot checks may be unavailable. Trend sources can change their markup or block requests; choose another source or enter a topic when that happens. Review factual claims and source attribution before publishing generated articles.

## Verification

```powershell
python -m pytest tests -q -p no:cacheprovider
```

Tests create temporary databases and block unmocked HTTP traffic. They cover API validation/authentication, source grounding, cancellation, additive migration, scheduler intervals/persistence/recovery, model adapter compatibility, extraction and publishing sanitization. Original integration checks are retained under `tests/manual/` as a reference and excluded from discovery.

## Project layout

```text
api/         HTTP routes and application lifecycle
core/        Settings, model requests and serial scheduler
analyzer/    Source headline extraction
generator/   Article prompts and generation
scraper/     Public source extraction and trend adapters
database/    Models, transactions and explicit WordPress delivery
templates/   Local HTML, JavaScript and CSS
tests/       Isolated regressions and original test reference
main.py      Application launcher
```

The original project embedded Hugging Face and WordPress credentials. They have been removed from the public source; replace those credentials before configuring your installation. Personal content and logs are kept locally.

Checked on Windows with Python 3.13.5 (Conda base): **41 tests passed**.

Source redirects now share the remaining request budget instead of each receiving a fresh timeout. WordPress receipts are checked for a positive integer post ID and a recognized status before delivery is reported as successful. These checks preserve local articles on bad remote responses; no live publishing is performed by the test suite.

No license file is included.

Incomplete generation responses never substitute the newest draft or a same-topic draft from the library. A missing response body may be recovered only by its exact returned ID. Invalid or blank bodies produce an error, preserve the input and keep any previous saved draft explicitly labelled as retained. This behavior was checked in the browser with synthetic responses; no live model or WordPress delivery was invoked.

Library refreshes apply only the latest request, preventing an older response from replacing newer results. Optional Node-based frontend regressions cover draft ownership and out-of-order refreshes when Node is already available. Node is not required to run the application.

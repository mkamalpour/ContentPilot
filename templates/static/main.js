"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  let runtime = {};
  try {
    runtime = JSON.parse($("contentpilot-runtime").textContent);
  } catch {}
  let apiKey = runtime.apiKey || "",
    page = "studio",
    mode = "url",
    contents = [],
    selectedId = null,
    health = {},
    jobsActive = false;
  const state = { generating: false, chatting: false, scheduling: false };
  function notice(message, error = false) {
    const n = $("notice");
    n.textContent = message;
    n.className = error ? "error" : "";
    n.hidden = !message;
  }
  async function request(path, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 330000);
    try {
      const response = await fetch(path, {
        ...options,
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
          ...(apiKey ? { "X-API-Key": apiKey } : {}),
          ...options.headers,
        },
      });
      let data;
      const text = await response.text();
      try {
        data = JSON.parse(text);
      } catch {
        data = { detail: text };
      }
      if (!response.ok) {
        let detail =
          data.detail || data.error || `Request failed (${response.status})`;
        if (Array.isArray(detail))
          detail = detail.map((x) => x.msg || String(x)).join("; ");
        else if (typeof detail !== "string") detail = JSON.stringify(detail);
        throw new Error(detail);
      }
      return data;
    } catch (error) {
      if (error.name === "AbortError")
        throw new Error(
          "This request took too long. Your input is preserved; check Activity before trying again.",
        );
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }
  const post = (path, data = {}) =>
    request(path, { method: "POST", body: JSON.stringify(data) });
  function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function button(text, fn, kind = "secondary") {
    const b = el("button", text, kind);
    b.type = "button";
    b.addEventListener("click", async () => {
      b.disabled = true;
      try {
        await fn();
      } catch (e) {
        notice(e.message, true);
      } finally {
        b.disabled = false;
      }
    });
    return b;
  }
  const dateLabel = (value) => {
    if (!value) return "Not available";
    const date = new Date(value);
    return Number.isNaN(date.getTime())
      ? String(value)
      : date.toLocaleString(undefined, {
          dateStyle: "medium",
          timeStyle: "short",
        });
  };
  function setPage(next) {
    page = next;
    document
      .querySelectorAll("[data-view]")
      .forEach((n) => (n.hidden = n.dataset.view !== page));
    document.querySelectorAll("nav [data-page]").forEach((n) => {
      n.classList.toggle("active", n.dataset.page === page);
      if (n.dataset.page === page) n.setAttribute("aria-current", "page");
      else n.removeAttribute("aria-current");
    });
    $("breadcrumb").textContent =
      "Workspace / " +
      {
        studio: "Studio",
        library: "Library",
        trends: "Discover trends",
        automations: "Automations",
        assistant: "Assistant",
        activity: "Activity",
        settings: "Settings",
      }[page];
    notice("");
    if (page === "library") loadLibrary();
    if (page === "automations") {
      loadJobs();
      loadClock();
    }
    if (page === "activity") loadLogs();
    if (page === "settings") loadHealth();
  }
  document
    .querySelectorAll("[data-page]")
    .forEach((n) => n.addEventListener("click", () => setPage(n.dataset.page)));
  document.querySelector(".brand").addEventListener("click", (event) => {
    event.preventDefault();
    setPage("studio");
  });
  function setMode(next) {
    mode = next;
    ["url", "topic"].forEach((m) => {
      $("mode-" + m).classList.toggle("selected", m === mode);
      $("mode-" + m).setAttribute("aria-pressed", String(m === mode));
    });
    $("source-label").textContent =
      mode === "url" ? "Source URL" : "Topic or idea";
    $("source-input").placeholder =
      mode === "url"
        ? "https://example.com/a-story-worth-sharing"
        : "What would you like to explore?";
    $("source-help").textContent =
      mode === "url"
        ? "Use a public article or page as your starting point."
        : "Be specific: give your draft a clear subject and a fresh angle.";
  }
  $("mode-url").onclick = () => setMode("url");
  $("mode-topic").onclick = () => setMode("topic");
  function articleActions(record, target) {
    target.replaceChildren();
    target.append(
      button("Copy draft", async () => {
        await navigator.clipboard.writeText(record.body || "");
        notice("Draft copied to your clipboard.");
      }),
      button("Download .md", () => {
        const blob = new Blob(
          [`# ${record.topic || "Untitled draft"}\n\n${record.body || ""}`],
          { type: "text/markdown;charset=utf-8" },
        );
        const url = URL.createObjectURL(blob),
          a = el("a");
        a.href = url;
        a.download =
          (record.topic || "draft").replace(/[^a-z0-9-]/gi, "-").slice(0, 70) +
          ".md";
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }),
    );
    if (record.id != null && health.wordpress_configured) {
      target.append(
        button("Send to WordPress drafts", () => publish(record, "draft")),
        button("Publish on WordPress", () => publish(record, "publish")),
      );
    }
    if (target.id === "detail-actions" && record.id != null)
      target.append(
        button(
          "Delete draft",
          async () => {
            if (!confirm("Delete this draft permanently?")) return;
            await request(`/contents/${encodeURIComponent(record.id)}`, {
              method: "DELETE",
            });
            selectedId = null;
            $("library-detail").hidden = true;
            $("library-empty").hidden = false;
            await loadLibrary();
            notice("Draft deleted.");
          },
          "danger",
        ),
      );
  }
  async function publish(record, status) {
    if (
      status === "publish" &&
      !confirm("Publish this draft publicly on your WordPress site now?")
    )
      return;
    const result = await post(
      `/contents/${encodeURIComponent(record.id)}/publish`,
      { status },
    );
    notice(
      status === "draft"
        ? "Draft sent to WordPress for review."
        : "Published on WordPress.",
    );
    if (result.url) {
      const link = el("a", "Open WordPress article");
      try {
        const url = new URL(result.url);
        if (["https:", "http:"].includes(url.protocol)) {
          link.href = url.href;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          $("notice").append(document.createTextNode(" "), link);
        }
      } catch {}
    }
  }
  function showDraft(record) {
    $("draft-empty").hidden = true;
    $("draft-content").hidden = false;
    $("draft-title").textContent = record.topic || "Your new draft";
    $("draft-meta").textContent = "Saved to your library";
    $("draft-body").textContent = record.body || "";
    articleActions(record, $("draft-actions"));
  }
  function unwrapDraft(result, input) {
    if (result && typeof result === "object") {
      const item =
        result.content && typeof result.content === "object"
          ? result.content
          : result.article && typeof result.article === "object"
            ? result.article
            : result;
      return {
        ...item,
        topic: item.topic || item.title || input,
        body:
          item.body ||
          item.generated_content ||
          item.content ||
          item.result ||
          "",
      };
    }
    return { topic: input, body: String(result || "") };
  }
  $("generate-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (state.generating) return;
    const input = $("source-input").value.trim();
    if (!input) return;
    if (mode === "url") {
      try {
        const u = new URL(input);
        if (!["https:", "http:"].includes(u.protocol)) throw Error();
      } catch {
        notice("Enter a complete http or https source URL.", true);
        return;
      }
    }
    state.generating = true;
    $("generate-form").setAttribute("aria-busy", "true");
    $("generate-button").disabled = true;
    $("generate-button").textContent = "Working on your draft...";
    notice("Researching and drafting. Your model may take a little time.");
    try {
      const result = await post(
        mode === "url" ? "/process" : "/generate_by_trend",
        mode === "url" ? { url: input } : { trend: input, source: "all" },
      );
      const record = unwrapDraft(result, input);
      await loadLibrary(false);
      const match =
        contents.find((x) => x.id === record.id) ||
        contents.find((x) => x.topic === record.topic) ||
        contents[0];
      if (!record.body && match) Object.assign(record, match);
      if (!record.body)
        throw new Error(
          "The server finished without returning a draft. Check your library and Activity.",
        );
      showDraft(record);
      const publicationError =
        result?.publication_error || record.publication_error;
      if (publicationError)
        notice(
          "Your draft was saved, but automatic WordPress delivery failed: " +
            String(publicationError),
          true,
        );
      else
        notice(
          health.auto_publish
            ? "Your draft is ready. Review the configured WordPress delivery status before publishing again."
            : "Your draft is ready. Review it before publishing.",
        );
    } catch (e) {
      notice(e.message, true);
    } finally {
      state.generating = false;
      $("generate-form").setAttribute("aria-busy", "false");
      $("generate-button").disabled = false;
      $("generate-button").textContent = "Create a draft \u2197";
    }
  });
  async function loadLibrary(report = true) {
    try {
      const data = await request("/contents?limit=500");
      contents = Array.isArray(data) ? data : data.contents || [];
      $("library-count").textContent = contents.length;
      renderLibrary();
    } catch (e) {
      if (report) notice(e.message, true);
    }
  }
  function renderLibrary() {
    const query = $("library-search").value.trim().toLowerCase();
    const rows = contents.filter((x) =>
      `${x.topic || ""} ${x.body || ""}`.toLowerCase().includes(query),
    );
    $("library-summary").textContent =
      `${rows.length} matching / ${contents.length} loaded${contents.length === 500 ? " (first 500 drafts)" : ""}`;
    const list = $("library-list");
    list.replaceChildren();
    if (!rows.length) {
      const empty = el("div", undefined, "empty");
      empty.append(
        el("h3", query ? "No matching drafts" : "Your library starts here."),
        el(
          "p",
          query
            ? "Try a different search."
            : "Create your first draft in the Studio.",
        ),
      );
      list.append(empty);
      return;
    }
    rows.forEach((record) => {
      const b = el(
        "button",
        undefined,
        "library-item" + (selectedId === record.id ? " selected" : ""),
      );
      b.type = "button";
      b.append(
        el("small", record.trend ? "TOPIC RESEARCH" : "SOURCE RESEARCH"),
        el("strong", record.topic || "Untitled draft"),
        el("small", dateLabel(record.created_at)),
      );
      b.onclick = () => {
        selectedId = record.id;
        $("library-empty").hidden = true;
        $("library-detail").hidden = false;
        $("detail-title").textContent = record.topic || "Untitled draft";
        $("detail-meta").textContent = dateLabel(record.created_at);
        $("detail-body").textContent = record.body || "";
        articleActions(record, $("detail-actions"));
        renderLibrary();
      };
      list.append(b);
    });
  }
  $("library-search").addEventListener("input", renderLibrary);
  $("refresh-library").onclick = () => loadLibrary();
  $("clear-library").onclick = async () => {
    if (
      prompt("Type DELETE to permanently clear your entire draft library.") !==
      "DELETE"
    )
      return;
    try {
      await request("/flush_db", { method: "DELETE" });
      selectedId = null;
      $("library-detail").hidden = true;
      $("library-empty").hidden = false;
      await loadLibrary();
      notice("All drafts deleted.");
    } catch (e) {
      notice(e.message, true);
    }
  };
  $("refresh-trends").onclick = async () => {
    const b = $("refresh-trends");
    b.disabled = true;
    notice("Discovering current topics...");
    try {
      const data = await request(
        `/trends?source=${encodeURIComponent($("trend-source").value)}`,
      );
      const trends = Array.isArray(data) ? data : data.trends || [];
      const list = $("trends-list");
      list.replaceChildren();
      list.classList.toggle("empty", !trends.length);
      if (!trends.length) {
        list.append(
          el("h3", "No topics available right now."),
          el("p", "Try another source or bring your own idea to the Studio."),
        );
      }
      trends.forEach((item, index) => {
        const topic =
          typeof item === "string"
            ? item
            : item.topic ||
              item.title ||
              item.name ||
              item.trend ||
              "Untitled topic";
        const row = el("article", undefined, "trend-row"),
          text = el("div");
        text.append(
          el(
            "p",
            String(index + 1).padStart(2, "0") +
              " / " +
              (item.source || $("trend-source").selectedOptions[0].text),
          ),
          el("h3", topic),
        );
        row.append(
          text,
          button(
            "Draft this topic \u2197",
            () => {
              setPage("studio");
              setMode("topic");
              $("source-input").value = topic;
              $("source-input").focus();
            },
            "primary",
          ),
        );
        list.append(row);
      });
      notice("");
    } catch (e) {
      notice(e.message, true);
    } finally {
      b.disabled = false;
    }
  };
  const lines = (id) =>
    $(id)
      .value.split(/\r?\n/)
      .map((x) => x.trim())
      .filter(Boolean);
  const iso = (id) =>
    $(id).value ? new Date($(id).value).toISOString() : null;
  $("schedule-kind").onchange = () => {
    $("interval-field").hidden = $("schedule-kind").value !== "interval";
    $("date-field").hidden = $("schedule-kind").value !== "date";
  };
  $("schedule-form").onsubmit = async (event) => {
    event.preventDefault();
    if (state.scheduling) return;
    const job = $("job-name").value,
      urls = lines("schedule-urls"),
      topics = lines("schedule-topics");
    if (
      (job === "process" && !urls.length) ||
      (job === "trend" && !topics.length) ||
      (job === "all" && !urls.length && !topics.length)
    ) {
      notice(
        "Add at least one source URL or topic for the selected task.",
        true,
      );
      return;
    }
    if ($("schedule-kind").value === "date" && !$("schedule-date").value) {
      notice("Choose a date and time for this task.", true);
      return;
    }
    state.scheduling = true;
    const b = event.submitter;
    b.disabled = true;
    try {
      const data = {
        job_name: job,
        interval:
          $("schedule-kind").value === "interval"
            ? $("schedule-interval").value
            : null,
        datetimes:
          $("schedule-kind").value === "date" ? [iso("schedule-date")] : null,
        start_datetime: iso("schedule-start"),
        end_datetime: iso("schedule-end"),
        enabled: $("schedule-enabled").checked,
        payload: { url: urls, trend: topics, source: "all" },
      };
      await post("/schedule", data);
      await loadJobs();
      notice(
        data.enabled
          ? "Schedule saved and enabled."
          : "Schedule saved in a disabled state.",
      );
    } catch (e) {
      notice(e.message, true);
    } finally {
      state.scheduling = false;
      b.disabled = false;
    }
  };
  async function loadJobs() {
    try {
      const data = await request("/job_status");
      const jobs = data.active_jobs || [];
      jobsActive = (data.active_jobs_count ?? jobs.length) > 0;
      $("job-count").textContent =
        `${data.active_jobs_count ?? jobs.length} active`;
      const list = $("job-list");
      list.replaceChildren();
      list.className = jobs.length ? "" : "empty";
      if (!jobs.length)
        list.append(
          el("p", "No active schedules. Start with a task and a time."),
        );
      jobs.forEach((job) => {
        const row = el("div", undefined, "job-row");
        row.append(
          el(
            "h3",
            {
              all: "URLs and topics",
              process: "Draft from URLs",
              trend: "Draft from topics",
            }[job.job_name] || job.job_name,
          ),
          el("p", "Status: " + (job.status || "Scheduled")),
          el("p", "Next run: " + dateLabel(job.next_trigger)),
        );
        if (
          job.waiting_for &&
          (!Array.isArray(job.waiting_for) || job.waiting_for.length)
        )
          row.append(
            el(
              "p",
              typeof job.waiting_for === "string"
                ? job.waiting_for
                : JSON.stringify(job.waiting_for),
            ),
          );
        if (job.execution_info) {
          if (typeof job.execution_info === "string")
            row.append(el("p", job.execution_info));
          else {
            if (job.execution_info.last_run)
              row.append(
                el("p", "Last run: " + dateLabel(job.execution_info.last_run)),
              );
            if (job.execution_info.error)
              row.append(
                el(
                  "p",
                  "Task failed: " + job.execution_info.error,
                  "job-error",
                ),
              );
          }
        }
        list.append(row);
      });
      $("cancel-jobs").disabled = !jobsActive;
    } catch (e) {
      if (page === "automations") notice(e.message, true);
    }
  }
  $("refresh-jobs").onclick = loadJobs;
  $("cancel-jobs").onclick = async () => {
    if (
      !confirm("Cancel all scheduled tasks? A task already running may finish.")
    )
      return;
    try {
      await post("/cancel_all_jobs");
      await loadJobs();
      notice("Scheduled tasks cancelled.");
    } catch (e) {
      notice(e.message, true);
    }
  };
  async function loadClock() {
    try {
      const data = await request("/current_time");
      $("clock-status").textContent =
        (data.simulated ? "Test clock: " : "Real time: ") +
        dateLabel(data.current_time);
    } catch (e) {
      notice(e.message, true);
    }
  }
  $("set-clock").onclick = async () => {
    if (!$("clock-input").value) {
      notice("Choose a simulated time first.", true);
      return;
    }
    try {
      await post("/update_time", { current_time: iso("clock-input") });
      await loadClock();
      notice("Test clock applied.");
    } catch (e) {
      notice(e.message, true);
    }
  };
  $("reset-clock").onclick = async () => {
    try {
      await post("/update_time", { current_time: null });
      await loadClock();
      notice("Real time restored.");
    } catch (e) {
      notice(e.message, true);
    }
  };
  $("chat-form").onsubmit = async (event) => {
    event.preventDefault();
    if (state.chatting) return;
    const text = $("chat-input").value.trim();
    if (!text) return;
    state.chatting = true;
    const b = event.submitter;
    b.disabled = true;
    const box = $("chat-messages");
    box.querySelector(".chat-intro")?.remove();
    function message(role, text) {
      const n = el("div", undefined, "message " + role);
      n.append(
        el("strong", role === "user" ? "YOU" : "ASSISTANT"),
        el("p", text),
      );
      box.append(n);
      box.scrollTop = box.scrollHeight;
    }
    message("user", text);
    notice("Your assistant is thinking...");
    try {
      const data = await post("/chat", { message: text });
      message(
        "assistant",
        data.reply || data.response || "No response returned.",
      );
      $("chat-input").value = "";
      notice("");
    } catch (e) {
      notice(e.message, true);
    } finally {
      state.chatting = false;
      b.disabled = false;
    }
  };
  async function loadLogs() {
    try {
      let data = await request("/logs?from_line=0&max_lines=100");
      if (data.total_lines > 100)
        data = await request(
          `/logs?from_line=${Math.max(0, data.total_lines - 100)}&max_lines=100`,
        );
      const lines = Array.isArray(data.lines) ? data.lines : [];
      $("activity-log").textContent = lines.length
        ? lines
            .map((x) => (typeof x === "string" ? x : JSON.stringify(x)))
            .join("\n")
        : "No recent activity. Your next task will appear here.";
    } catch (e) {
      notice(e.message, true);
    }
  }
  $("refresh-logs").onclick = loadLogs;
  async function loadHealth() {
    try {
      health = await request("/health");
      document.querySelector(".editor-note p").textContent = health.auto_publish
        ? "Automatic WordPress delivery is enabled. New drafts may be sent to your site."
        : "Your draft stays in your library. Publishing is a separate, deliberate step.";
      $("connection").textContent = "Workspace connected";
      $("connection-dot").classList.add("online");
      $("model-summary").textContent =
        `Model / ${health.model_name || health.model_provider || "Configured"}`;
      const dl = $("connection-details");
      dl.replaceChildren();
      [
        ["Model provider", health.model_provider || "Not configured"],
        ["Model", health.model_name || "Not configured"],
        [
          "WordPress",
          health.wordpress_configured
            ? "Configured (not verified)"
            : "Not configured",
        ],
        [
          "Automatic publishing",
          health.auto_publish ? "Enabled on server" : "Disabled",
        ],
      ].forEach(([k, v]) => dl.append(el("dt", k), el("dd", v)));
    } catch (e) {
      $("connection").textContent = "Connection needs attention";
      $("connection-dot").classList.remove("online");
      $("model-summary").textContent = "Check workspace settings";
      notice(e.message, true);
    }
  }
  $("key-form").onsubmit = async (event) => {
    event.preventDefault();
    apiKey = $("api-key").value.trim();
    $("api-key").value = "";
    notice("");
    await loadHealth();
    await loadLibrary(true);
  };
  setInterval(() => {
    if (!document.hidden && (page === "automations" || jobsActive)) loadJobs();
  }, 5000);
  setInterval(() => {
    if (!document.hidden && page === "activity") loadLogs();
  }, 10000);
  loadHealth();
  loadLibrary(false);
})();

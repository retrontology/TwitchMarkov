// TwitchMarkov admin UI. Vanilla JS, no build step, no dependencies.
// DOM is always built with h()/text nodes — never innerHTML with API data.

(function () {
  "use strict";

  // ---------------------------------------------------------------------
  // DOM helpers
  // ---------------------------------------------------------------------

  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v === null || v === undefined || v === false) continue;
        if (k === "class") el.className = v;
        else if (k === "value") el.value = v;
        else if (k === "checked") el.checked = v;
        else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
        else el.setAttribute(k, String(v));
      }
    }
    for (const child of children.flat(Infinity)) {
      if (child === null || child === undefined || child === false) continue;
      el.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return el;
  }

  function relativeTime(iso) {
    if (!iso) return "never";
    const then = new Date(iso).getTime();
    if (Number.isNaN(then)) return iso;
    const diffSec = Math.max(0, Math.floor((Date.now() - then) / 1000));
    if (diffSec < 10) return "just now";
    if (diffSec < 60) return `${diffSec}s ago`;
    const min = Math.floor(diffSec / 60);
    if (min < 60) return `${min}m ago`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr}h ago`;
    const day = Math.floor(hr / 24);
    return `${day}d ago`;
  }

  // ---------------------------------------------------------------------
  // API layer
  // ---------------------------------------------------------------------

  class ApiError extends Error {
    constructor(status, detail) {
      super(detail);
      this.status = status;
      this.detail = detail;
    }
  }

  async function api(method, path, body) {
    const opts = { method, credentials: "same-origin", headers: {} };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    let res;
    try {
      res = await fetch(path, opts);
    } catch (err) {
      throw new ApiError(0, "Could not reach the server. Check your connection and try again.");
    }
    if (res.status === 204) return null;
    const text = await res.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (err) {
        data = null;
      }
    }
    if (!res.ok) {
      const detail = data && typeof data.detail === "string" ? data.detail : `Request failed (${res.status}).`;
      throw new ApiError(res.status, detail);
    }
    return data;
  }

  function errText(e) {
    if (e instanceof ApiError) return e.detail;
    return (e && e.message) || "Something went wrong.";
  }

  // ---------------------------------------------------------------------
  // Toasts
  // ---------------------------------------------------------------------

  let toastTimer = null;

  function toast(message, isError) {
    const region = document.getElementById("toast");
    if (!region) return;
    window.clearTimeout(toastTimer);
    const node = h(
      "div",
      { class: "toast" + (isError ? " toast-error" : "") },
      h("span", {}, message),
      h(
        "button",
        { class: "toast-close", type: "button", "aria-label": "Dismiss", onclick: () => region.replaceChildren() },
        "×"
      )
    );
    region.replaceChildren(node);
    toastTimer = window.setTimeout(() => region.replaceChildren(), 6000);
  }

  function handleError(e) {
    if (e instanceof ApiError && e.status === 401) {
      renderRoute();
      return;
    }
    toast(errText(e), true);
  }

  // ---------------------------------------------------------------------
  // Settings form (shared by channel detail + admin defaults)
  // ---------------------------------------------------------------------

  const SETTINGS_FIELDS = [
    { key: "send_messages", label: "Send messages", type: "bool", help: "Let the bot post generated messages in chat." },
    { key: "unique", label: "Require unique messages", type: "bool", help: "Only send messages that differ from recent history." },
    { key: "generate_on", label: "Generate every N messages", type: "int", min: 1, help: "Automatically generate a message after this many chat messages." },
    { key: "clear_logs_after", label: "Clear corpus after generating", type: "bool", help: "Wipe the stored messages every time one is generated." },
    { key: "ignored_users", label: "Ignored users", type: "lines", help: "Logins to exclude from the corpus, one per line." },
    { key: "percent_unique", label: "Uniqueness threshold (%)", type: "float", min: 0, max: 100, step: 0.1, help: "Minimum share of new words required in a generated message." },
    { key: "allow_mentions", label: "Allow @mentions", type: "bool", help: "Allow generated messages to contain @mentions." },
    { key: "state_size", label: "Markov state size", type: "int", min: 1, max: 5, help: "Number of prior words used to choose the next word." },
    { key: "times_to_try", label: "Generation attempts", type: "int", min: 1, help: "How many times to try generating a message that clears the uniqueness threshold." },
    { key: "cull_over", label: "Cull corpus over (messages)", type: "int", min: 1, help: "Trim the corpus once it grows past this many messages." },
    { key: "time_to_cull", label: "Cull after (seconds)", type: "int", min: 0, help: "Also trim the corpus this many seconds after the last cull. 0 disables." },
    { key: "cooldown_speak", label: "Cooldown: !speak (seconds)", type: "int", min: 0, help: "Minimum time between !speak uses." },
    { key: "cooldown_commands", label: "Cooldown: mod commands (seconds)", type: "int", min: 0, help: "Minimum time between moderator command uses." },
    { key: "cooldown_reply", label: "Cooldown: replies (seconds)", type: "int", min: 0, help: "Minimum time between automatic reply messages." },
  ];

  function settingsForm(initial, onSubmit) {
    const inputs = {};
    const fields = SETTINGS_FIELDS.map((f) => {
      let input;
      if (f.type === "bool") {
        input = h("input", { type: "checkbox", id: `f-${f.key}`, checked: !!initial[f.key] });
      } else if (f.type === "lines") {
        input = h("textarea", {
          id: `f-${f.key}`,
          class: "textarea mono",
          rows: "4",
          value: (initial[f.key] || []).join("\n"),
        });
      } else {
        const attrs = { type: "number", id: `f-${f.key}`, class: "input", value: initial[f.key], required: true };
        if (f.min !== undefined) attrs.min = f.min;
        if (f.max !== undefined) attrs.max = f.max;
        attrs.step = f.step !== undefined ? f.step : f.type === "float" ? "any" : 1;
        input = h("input", attrs);
      }
      inputs[f.key] = input;
      const body =
        f.type === "bool"
          ? [h("label", { class: "field-check", for: `f-${f.key}` }, input, f.label)]
          : [h("label", { class: "field-label", for: `f-${f.key}` }, f.label), input];
      return h(
        "div",
        { class: "field" + (f.type === "bool" ? " field-bool" : "") + (f.type === "lines" ? " field-lines" : "") },
        body,
        f.help ? h("div", { class: "field-help" }, f.help) : null
      );
    });

    const submitBtn = h("button", { class: "btn btn-primary", type: "submit" }, "Save settings");
    const form = h(
      "form",
      {
        class: "settings-grid",
        onsubmit: async (ev) => {
          ev.preventDefault();
          const values = {};
          for (const f of SETTINGS_FIELDS) {
            const el = inputs[f.key];
            if (f.type === "bool") values[f.key] = el.checked;
            else if (f.type === "lines")
              values[f.key] = el.value
                .split("\n")
                .map((s) => s.trim())
                .filter(Boolean);
            else if (f.type === "float") values[f.key] = parseFloat(el.value);
            else values[f.key] = parseInt(el.value, 10);
          }
          submitBtn.setAttribute("disabled", "");
          try {
            await onSubmit(values);
          } catch (e) {
            handleError(e);
          } finally {
            submitBtn.removeAttribute("disabled");
          }
        },
      },
      fields,
      h("div", { class: "form-actions" }, submitBtn)
    );
    return form;
  }

  function blacklistForm(initial, onSubmit) {
    const textarea = h("textarea", { class: "textarea mono", rows: "6", value: initial.join("\n") });
    const submitBtn = h("button", { class: "btn btn-primary", type: "submit" }, "Save blacklist");
    return h(
      "form",
      {
        onsubmit: async (ev) => {
          ev.preventDefault();
          const patterns = textarea.value
            .split("\n")
            .map((s) => s.trim())
            .filter(Boolean);
          submitBtn.setAttribute("disabled", "");
          try {
            await onSubmit(patterns);
          } catch (e) {
            handleError(e);
          } finally {
            submitBtn.removeAttribute("disabled");
          }
        },
      },
      h("p", { class: "field-help" }, "One pattern per line. Messages matching any pattern are ignored."),
      textarea,
      h("div", { class: "form-actions" }, submitBtn)
    );
  }

  // ---------------------------------------------------------------------
  // Small shared pieces
  // ---------------------------------------------------------------------

  function SectionTitle(text) {
    return h("h2", { class: "section-title" }, text);
  }

  function Stat(label, value) {
    return h("div", { class: "stat" }, h("div", { class: "stat-label" }, label), h("div", { class: "stat-value" }, value));
  }

  function StatusDot(on, label) {
    return h("span", { class: "dot-label" }, h("span", { class: "dot " + (on ? "dot-on" : "dot-off") }), label);
  }

  // ---------------------------------------------------------------------
  // Header + login views
  // ---------------------------------------------------------------------

  function currentRouteIsList() {
    return matchRoute(location.hash).view === ChannelListView;
  }

  async function onLogout() {
    try {
      await api("POST", "/auth/logout");
    } catch (e) {
      // Best-effort: still send the user back to a logged-out view below.
    }
    location.hash = "#/";
    renderRoute();
  }

  function Header(me) {
    return h(
      "header",
      { class: "appbar" },
      h(
        "div",
        { class: "appbar-inner" },
        h("a", { class: "brand", href: "#/" }, h("span", { class: "brand-tick" }), "TwitchMarkov"),
        h(
          "nav",
          { class: "nav" },
          h("a", { href: "#/", class: currentRouteIsList() ? "active" : "" }, "Channels"),
          me.is_admin ? h("a", { href: "#/admin", class: location.hash.startsWith("#/admin") ? "active" : "" }, "Admin") : null
        ),
        h(
          "div",
          { class: "account" },
          h("span", { class: "account-name" }, me.display_name),
          me.is_admin ? h("span", { class: "badge badge-admin" }, "Admin") : null,
          h("button", { class: "btn btn-ghost", type: "button", onclick: onLogout }, "Log out")
        )
      )
    );
  }

  function LoginView() {
    const next = encodeURIComponent(location.pathname + location.hash);
    return h(
      "div",
      { class: "auth-shell" },
      h(
        "div",
        { class: "auth-card" },
        h("div", { class: "brand brand-lg" }, h("span", { class: "brand-tick" }), "TwitchMarkov"),
        h("p", { class: "muted" }, "Sign in with your Twitch account to manage your bot and channels."),
        h("a", { class: "btn btn-primary btn-block", href: `/auth/login?next=${next}` }, "Sign in with Twitch")
      )
    );
  }

  // ---------------------------------------------------------------------
  // Channel list view
  // ---------------------------------------------------------------------

  function AddChannelForm() {
    const input = h("input", {
      type: "text",
      id: "add-channel-login",
      class: "input",
      placeholder: "twitch login",
      autocomplete: "off",
      required: true,
    });
    const submitBtn = h("button", { class: "btn btn-primary", type: "submit" }, "Add channel");
    return h(
      "form",
      {
        class: "inline-form",
        onsubmit: async (ev) => {
          ev.preventDefault();
          const login = input.value.trim().toLowerCase();
          if (!login) return;
          submitBtn.setAttribute("disabled", "");
          try {
            const channel = await api("POST", "/api/channels", { login });
            toast(`Added ${channel.display_name}.`);
            location.hash = `#/channels/${channel.id}`;
            renderRoute();
          } catch (e) {
            handleError(e);
          } finally {
            submitBtn.removeAttribute("disabled");
          }
        },
      },
      h("label", { class: "sr-only", for: "add-channel-login" }, "Twitch login"),
      input,
      submitBtn
    );
  }

  function ChannelTable(channels, joinedLogins) {
    const rows = channels.map((c) => {
      const go = () => {
        location.hash = `#/channels/${c.id}`;
      };
      return h(
        "tr",
        {
          class: "row-link",
          tabindex: "0",
          onclick: go,
          onkeydown: (ev) => {
            if (ev.key === "Enter") go();
          },
        },
        h("td", {}, h("div", { class: "cell-name" }, c.display_name), h("div", { class: "cell-login" }, "@" + c.login)),
        h("td", {}, StatusDot(c.enabled, c.enabled ? "Enabled" : "Disabled")),
        h("td", {}, StatusDot(joinedLogins.has(c.login), joinedLogins.has(c.login) ? "Joined" : "Not joined"))
      );
    });
    return h(
      "div",
      { class: "table-wrap" },
      h(
        "table",
        { class: "table" },
        h("thead", {}, h("tr", {}, h("th", {}, "Channel"), h("th", {}, "Status"), h("th", {}, "Bot"))),
        h("tbody", {}, rows)
      )
    );
  }

  async function ChannelListView(params, me) {
    const [channels, bot] = await Promise.all([api("GET", "/api/channels"), api("GET", "/api/bot")]);
    const joined = new Set(bot.joined);
    const page = h("div", { class: "page" });
    page.appendChild(h("div", { class: "page-head" }, h("h1", {}, "Channels")));
    if (me.is_admin) page.appendChild(AddChannelForm());
    if (channels.length === 0) {
      page.appendChild(
        h(
          "p",
          { class: "empty" },
          me.is_admin ? "No channels yet. Add one above to get started." : "No channels configured yet."
        )
      );
    } else {
      page.appendChild(ChannelTable(channels, joined));
    }
    return page;
  }

  // ---------------------------------------------------------------------
  // Channel detail view
  // ---------------------------------------------------------------------

  function StatusStripContent(stats) {
    return h(
      "div",
      { class: "stat-row" },
      Stat("Bot", stats.bot_state),
      Stat("Joined", stats.joined ? "Yes" : "No"),
      Stat("Corpus", String(stats.corpus_size)),
      Stat("Since last generate", String(stats.messages_since_generate)),
      Stat("Last generated", stats.last_generated_at ? relativeTime(stats.last_generated_at) : "never")
    );
  }

  async function refreshStats(channelId, node) {
    try {
      const stats = await api("GET", `/api/channels/${channelId}/stats`);
      node.replaceChildren(StatusStripContent(stats));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        handleError(e);
        return;
      }
      node.replaceChildren(h("p", { class: "muted" }, errText(e)));
    }
  }

  function DetailHeader(channel) {
    const toggle = h("input", {
      type: "checkbox",
      checked: channel.enabled,
      onchange: async (ev) => {
        const next = ev.target.checked;
        try {
          await api("PATCH", `/api/channels/${channel.id}`, { enabled: next });
          toast(next ? "Channel enabled." : "Channel disabled.");
        } catch (e) {
          ev.target.checked = !next;
          handleError(e);
        }
      },
    });
    return h(
      "div",
      { class: "detail-head" },
      h("div", {}, h("h1", {}, channel.display_name), h("div", { class: "muted mono" }, "@" + channel.login)),
      h("label", { class: "switch" }, toggle, h("span", { class: "switch-track" }), h("span", { class: "switch-label" }, "Enabled"))
    );
  }

  function GenerateSection(channelId) {
    const result = h("div", { class: "generate-result" });

    async function doGenerate(send) {
      try {
        const res = await api("POST", `/api/channels/${channelId}/generate`, { send });
        result.replaceChildren(
          res.content
            ? h(
                "div",
                { class: "generated-line" },
                h("span", { class: "mono" }, res.content),
                h("span", { class: "badge " + (res.sent ? "badge-good" : "badge-muted") }, res.sent ? "Sent" : "Not sent")
              )
            : h("p", { class: "muted" }, "No message could be generated from the current corpus.")
        );
      } catch (e) {
        handleError(e);
      }
    }

    async function doWipe() {
      if (!window.confirm("Wipe the cached message corpus for this channel? This cannot be undone.")) return;
      try {
        await api("POST", `/api/channels/${channelId}/wipe`);
        toast("Corpus wiped.");
        result.replaceChildren();
      } catch (e) {
        handleError(e);
      }
    }

    return h(
      "section",
      { class: "section" },
      SectionTitle("Generate"),
      h(
        "div",
        { class: "button-row" },
        h("button", { class: "btn", type: "button", onclick: () => doGenerate(false) }, "Generate"),
        h("button", { class: "btn btn-primary", type: "button", onclick: () => doGenerate(true) }, "Generate & send"),
        h("button", { class: "btn btn-danger", type: "button", onclick: doWipe }, "Wipe corpus")
      ),
      result
    );
  }

  function SettingsSection(channel) {
    const form = settingsForm(channel.settings, async (values) => {
      await api("PATCH", `/api/channels/${channel.id}`, { settings: values });
      toast("Settings saved.");
    });
    return h("section", { class: "section" }, SectionTitle("Settings"), form);
  }

  function BlacklistSection(channelId, patterns) {
    const form = blacklistForm(patterns, async (next) => {
      await api("PUT", `/api/channels/${channelId}/blacklist`, { patterns: next });
      toast("Blacklist saved.");
    });
    return h("section", { class: "section" }, SectionTitle("Blacklist"), form);
  }

  function GeneratedItem(item) {
    return h(
      "li",
      { class: "generated-item" },
      h("div", { class: "mono generated-content" }, item.content),
      h(
        "div",
        { class: "generated-meta" },
        item.target ? h("span", {}, "to " + item.target) : h("span", {}, "no target"),
        h("span", { class: "badge " + (item.sent ? "badge-good" : "badge-muted") }, item.sent ? "Sent" : "Not sent"),
        h("span", {}, item.trigger),
        h("span", {}, relativeTime(item.created_at))
      )
    );
  }

  function RecentGeneratedSection(channelId) {
    const container = h("p", { class: "muted" }, "Loading…");
    api("GET", `/api/channels/${channelId}/generated?limit=20`)
      .then((items) => {
        if (items.length === 0) {
          container.replaceChildren(h("p", { class: "muted" }, "Nothing generated yet."));
          return;
        }
        container.replaceChildren(h("ul", { class: "generated-list" }, items.map(GeneratedItem)));
      })
      .catch((e) => {
        container.replaceChildren(h("p", { class: "muted" }, errText(e)));
        if (e instanceof ApiError && e.status === 401) handleError(e);
      });
    return h("section", { class: "section" }, SectionTitle("Recent generated"), container);
  }

  function RemoveChannelSection(channel) {
    return h(
      "section",
      { class: "section section-danger" },
      SectionTitle("Danger zone"),
      h(
        "p",
        { class: "field-help" },
        `Remove ${channel.display_name} from TwitchMarkov. The bot will leave the channel and stop generating messages.`
      ),
      h(
        "button",
        {
          class: "btn btn-danger",
          type: "button",
          onclick: async () => {
            if (!window.confirm(`Remove ${channel.display_name}? This cannot be undone.`)) return;
            try {
              await api("DELETE", `/api/channels/${channel.id}`);
              toast("Channel removed.");
              location.hash = "#/";
              renderRoute();
            } catch (e) {
              handleError(e);
            }
          },
        },
        "Remove channel"
      )
    );
  }

  async function ChannelDetailView(params, me) {
    const channelId = params.id;
    const [channel, blacklist] = await Promise.all([
      api("GET", `/api/channels/${channelId}`),
      api("GET", `/api/channels/${channelId}/blacklist`),
    ]);

    const page = h("div", { class: "page" });
    page.appendChild(h("a", { href: "#/", class: "back-link" }, "← Channels"));
    page.appendChild(DetailHeader(channel));

    const statusStrip = h("div", { class: "stat-row" }, h("span", { class: "muted" }, "Loading status…"));
    page.appendChild(statusStrip);
    refreshStats(channelId, statusStrip);
    pollTimer = window.setInterval(() => refreshStats(channelId, statusStrip), 10000);

    page.appendChild(GenerateSection(channelId));
    page.appendChild(SettingsSection(channel));
    page.appendChild(BlacklistSection(channelId, blacklist.patterns));
    page.appendChild(RecentGeneratedSection(channelId));
    if (me.is_admin) page.appendChild(RemoveChannelSection(channel));
    return page;
  }

  // ---------------------------------------------------------------------
  // Admin view
  // ---------------------------------------------------------------------

  const BOT_STATE_LABEL = {
    no_account: "No account connected",
    starting: "Starting",
    connected: "Connected",
    invalid_token: "Invalid token",
    stopped: "Stopped",
    error: "Error",
  };

  const BOT_STATE_TONE = {
    connected: "good",
    starting: "warn",
    no_account: "muted",
    stopped: "muted",
    invalid_token: "bad",
    error: "bad",
  };

  function BotAccountSection(bot) {
    const tone = BOT_STATE_TONE[bot.state] || "muted";
    const label = BOT_STATE_LABEL[bot.state] || bot.state;
    return h(
      "section",
      { class: "section" },
      h("div", { class: "section-title-row" }, SectionTitle("Bot account"), h("span", { class: "badge badge-" + tone }, label)),
      h(
        "div",
        { class: "stat-row" },
        Stat("Login", bot.login || "none"),
        bot.has_account ? Stat("Token valid", bot.account_valid ? "Yes" : "No") : null
      ),
      bot.error ? h("p", { class: "error-text" }, bot.error) : null,
      h(
        "div",
        { class: "button-row" },
        h("a", { class: "btn btn-primary", href: "/auth/bot/connect" }, bot.has_account ? "Reconnect" : "Connect bot account"),
        bot.has_account
          ? h(
              "button",
              {
                class: "btn btn-danger",
                type: "button",
                onclick: async () => {
                  if (!window.confirm("Disconnect the bot account? The bot will leave all channels until reconnected.")) return;
                  try {
                    await api("DELETE", "/api/bot/account");
                    toast("Bot account disconnected.");
                    renderRoute();
                  } catch (e) {
                    handleError(e);
                  }
                },
              },
              "Disconnect"
            )
          : null
      )
    );
  }

  async function AdminView(params, me) {
    if (!me.is_admin) {
      return h("div", { class: "page" }, h("p", { class: "empty" }, "Admins only."));
    }
    const [bot, defaults, blacklist] = await Promise.all([
      api("GET", "/api/bot"),
      api("GET", "/api/defaults"),
      api("GET", "/api/blacklist"),
    ]);
    const page = h("div", { class: "page" });
    page.appendChild(h("h1", {}, "Admin"));
    page.appendChild(BotAccountSection(bot));
    page.appendChild(
      h(
        "section",
        { class: "section" },
        SectionTitle("Default settings"),
        settingsForm(defaults, async (values) => {
          await api("PUT", "/api/defaults", values);
          toast("Defaults saved.");
        })
      )
    );
    page.appendChild(
      h(
        "section",
        { class: "section" },
        SectionTitle("Global blacklist"),
        blacklistForm(blacklist.patterns, async (patterns) => {
          await api("PUT", "/api/blacklist", { patterns });
          toast("Global blacklist saved.");
        })
      )
    );
    return page;
  }

  // ---------------------------------------------------------------------
  // Router
  // ---------------------------------------------------------------------

  function matchRoute(hash) {
    const value = hash || "#/";
    let m = value.match(/^#\/channels\/([^/]+)\/?$/);
    if (m) return { view: ChannelDetailView, params: { id: decodeURIComponent(m[1]) } };
    if (/^#\/admin\/?$/.test(value)) return { view: AdminView, params: {} };
    return { view: ChannelListView, params: {} };
  }

  let pollTimer = null;

  async function renderRoute() {
    if (pollTimer) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
    const root = document.getElementById("root");

    let me;
    try {
      me = await api("GET", "/api/me");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        root.replaceChildren(LoginView());
        return;
      }
      root.replaceChildren(h("div", { class: "page" }, h("p", { class: "error-text" }, errText(e))));
      return;
    }

    const { view, params } = matchRoute(location.hash);
    const main = h("main", { class: "main" });
    root.replaceChildren(h("div", { class: "app-shell" }, Header(me), main));

    try {
      const content = await view(params, me);
      main.replaceChildren(content);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        root.replaceChildren(LoginView());
        return;
      }
      main.replaceChildren(h("p", { class: "error-text" }, errText(e)));
      toast(errText(e), true);
    }
  }

  window.addEventListener("hashchange", renderRoute);
  document.addEventListener("DOMContentLoaded", renderRoute);
})();

/*
 * Push Alert TTS review card.
 *
 * Shows the alerts the AI worded recently (from the "AI review" sensor) with an
 * "Improve?" button on every row. Pressing it opens a text box: type what the AI
 * should do differently and press Send (or Enter). The correction is saved to the
 * AI memory together with the alert it is about (push_alert_tts.add_ai_correction),
 * and the AI words that alert again so you can see the effect. Nothing is spoken.
 *
 * Loaded automatically by the Push Alert TTS integration; no separate install.
 * Card config:
 *   type: custom:push-alert-tts-review-card
 *   entity: sensor.push_alert_tts_ai_review   # optional
 *   title: AI wording - last 3 days           # optional
 */

const CARD_TAG = "push-alert-tts-review-card";

const STYLE = `
  :host { display: block; }
  .wrap { padding: 0 16px 16px; overflow-x: auto; }
  .empty { padding: 8px 0; color: var(--secondary-text-color); }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th { text-align: left; font-weight: 500; color: var(--secondary-text-color);
       padding: 6px 8px; border-bottom: 1px solid var(--divider-color); }
  td { vertical-align: top; padding: 8px; border-bottom: 1px solid var(--divider-color); }
  td.time { white-space: nowrap; color: var(--secondary-text-color); }
  td.act { text-align: right; white-space: nowrap; }
  details summary { cursor: pointer; }
  .full { white-space: pre-wrap; word-break: break-word; margin-top: 4px;
          color: var(--secondary-text-color); font-size: 13px; }
  .note { display: block; margin-top: 4px; font-size: 12px; color: var(--secondary-text-color); }
  .later { color: var(--warning-color, #e0a000); }
  button { font: inherit; cursor: pointer; border-radius: 16px; padding: 4px 12px;
           border: 1px solid var(--primary-color); background: transparent;
           color: var(--primary-color); }
  button.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  button:disabled { opacity: 0.5; cursor: default; }
  tr.editor td { background: var(--secondary-background-color); }
  textarea { width: 100%; box-sizing: border-box; min-height: 56px; font: inherit;
             padding: 8px; border-radius: 6px; border: 1px solid var(--divider-color);
             background: var(--card-background-color); color: var(--primary-text-color); }
  .row { display: flex; gap: 8px; align-items: center; margin-top: 8px; flex-wrap: wrap; }
  .status { font-size: 13px; }
  .ok { color: var(--success-color, #2e7d32); }
  .err { color: var(--error-color, #c62828); }
  @media (max-width: 600px) {
    th.time, td.time { display: none; }
    td, th { padding: 6px 4px; }
  }
`;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const child of children.flat()) {
    if (child === undefined || child === null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function when(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value || "";
  return date.toLocaleString([], {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

function rowKey(row) {
  return `${row.received || ""}|${row.title || ""}`;
}

class PushAlertTtsReviewCard extends HTMLElement {
  setConfig(config) {
    this._config = {
      entity: "sensor.push_alert_tts_ai_review",
      title: "AI wording - last 3 days",
      ...(config || {}),
    };
    this._open = null; // key of the row whose editor is open
    this._drafts = {}; // key -> text being typed
    this._status = {}; // key -> {kind, text}
    this._busy = null;
    this._sig = null;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const state = hass.states[this._config.entity];
    const rows = (state && state.attributes && state.attributes.alerts) || [];
    const sig = JSON.stringify([
      state ? state.state : null,
      rows.map((r) => [r.received, r.ai_text, r.source]),
    ]);
    if (sig === this._sig) return;
    this._sig = sig;
    this._rows = rows;
    this._missing = !state;
    // Don't redraw under someone typing; redraw when they leave the box.
    const active = this.shadowRoot && this.shadowRoot.activeElement;
    if (active && active.tagName === "TEXTAREA") {
      this._pending = true;
      return;
    }
    this._render();
  }

  getCardSize() {
    return 2 + Math.min((this._rows || []).length, 10);
  }

  getGridOptions() {
    return { columns: "full", min_columns: 6 };
  }

  static getStubConfig() {
    return { entity: "sensor.push_alert_tts_ai_review" };
  }

  _toggle(key) {
    this._open = this._open === key ? null : key;
    this._render();
    if (this._open) {
      const box = this.shadowRoot.querySelector("textarea");
      if (box) box.focus();
    }
  }

  async _send(row) {
    const key = rowKey(row);
    const text = (this._drafts[key] || "").trim();
    if (!text || this._busy) return;
    this._busy = key;
    this._status[key] = { kind: "", text: "Saving and asking the AI to word it again..." };
    this._render();
    try {
      const res = await this._hass.callService(
        "push_alert_tts",
        "add_ai_correction",
        { text, received: row.received, title: row.title },
        undefined,
        false,
        true,
      );
      const r = (res && res.response) || {};
      let msg = "Saved to the AI memory.";
      if (r.new_wording) msg += ` New wording: "${r.new_wording}"`;
      else if (r.wording_reason) msg += ` The AI couldn't word it again just now (${String(r.wording_reason).replace(/_/g, " ")}).`;
      this._status[key] = { kind: "ok", text: msg };
      this._drafts[key] = "";
    } catch (err) {
      this._status[key] = {
        kind: "err",
        text: `Not saved: ${(err && err.message) || err}`,
      };
    }
    this._busy = null;
    this._render();
  }

  _editor(row) {
    const key = rowKey(row);
    const status = this._status[key];
    const box = el("textarea", {
      placeholder: "What should the AI say differently? e.g. Say Acme database, not Acme MySQL.",
      maxlength: "400",
      oninput: (ev) => { this._drafts[key] = ev.target.value; },
      onkeydown: (ev) => {
        if (ev.key === "Enter" && !ev.shiftKey) {
          ev.preventDefault();
          this._send(row);
        }
      },
      onblur: () => {
        if (this._pending) {
          this._pending = false;
          setTimeout(() => this._render(), 0);
        }
      },
    });
    box.value = this._drafts[key] || "";
    const busy = this._busy === key;
    return el("tr", { class: "editor" },
      el("td", { colspan: "4" },
        box,
        el("div", { class: "row" },
          el("button", { class: "primary", disabled: busy, onclick: () => this._send(row) }, busy ? "Saving..." : "Send"),
          el("button", { disabled: busy, onclick: () => this._toggle(key) }, "Close"),
          status ? el("span", { class: `status ${status.kind}` }, status.text) : null,
        ),
      ),
    );
  }

  _render() {
    if (!this.shadowRoot || !this._config) return;
    const rows = this._rows || [];
    const body = [];
    if (this._missing) {
      body.push(el("div", { class: "empty" }, `Entity not found: ${this._config.entity}`));
    } else if (!rows.length) {
      body.push(el("div", { class: "empty" }, "No alerts worded by the AI yet."));
    } else {
      const trs = [];
      for (const row of rows) {
        const key = rowKey(row);
        const alert = String(row.alert || row.title || "");
        const first = alert.split("\n")[0].slice(0, 120);
        const notAi = row.source !== "ai";
        trs.push(el("tr", {},
          el("td", { class: "time" }, when(row.received)),
          el("td", {},
            el("details", {}, el("summary", {}, first), el("div", { class: "full" }, alert)),
          ),
          el("td", {},
            row.ai_text || "-",
            notAi && row.spoken
              ? el("span", { class: "note" }, `Spoken instead: ${row.spoken}${row.reason ? ` (${String(row.reason).replace(/_/g, " ")})` : ""}`)
              : null,
            row.backfilled ? el("span", { class: "note later" }, "AI wording added later") : null,
          ),
          el("td", { class: "act" },
            el("button", { onclick: () => this._toggle(key) }, this._open === key ? "Close" : "Improve?"),
          ),
        ));
        if (this._open === key) trs.push(this._editor(row));
      }
      body.push(el("table", {},
        el("thead", {}, el("tr", {},
          el("th", { class: "time" }, "Received"),
          el("th", {}, "Alert received"),
          el("th", {}, "AI wording"),
          el("th", {}, ""),
        )),
        el("tbody", {}, trs),
      ));
    }
    const card = el("ha-card", { header: this._config.title || undefined },
      el("div", { class: "wrap" }, body),
    );
    this.shadowRoot.replaceChildren(el("style", {}, STYLE), card);
  }
}

if (!customElements.get(CARD_TAG)) {
  customElements.define(CARD_TAG, PushAlertTtsReviewCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: CARD_TAG,
    name: "Push Alert TTS review",
    description: "Recent AI wording of alerts, with an Improve? button per alert.",
  });
}

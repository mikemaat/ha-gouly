/**
 * Gouly Card - a light row that opens Home Assistant's own more-info dialog, with the Gouly
 * preset library added to it.
 *
 * The row is Home Assistant's tile card and the dialog is Home Assistant's more-info dialog;
 * this card adds an effect speed slider, favourite presets and the preset library, and on a
 * wide screen lays the dialog out in two columns.
 *
 * Uses the entities created by the ha-gouly integration:
 *   light.*                   the light
 *   select (preset_folder)    preset folder
 *   select (preset)           preset in that folder
 *   number (effect_speed)     effect speed
 *
 * Only `entity` is required; the rest are found on the same device by their translation key,
 * which stays put when the integration renames an entity (its entity id doesn't).
 *
 * Ships with the integration, which serves it and adds it to the dashboard resources.
 */

const VERSION = "6.2.2";
const DEFAULT_ICON = "mdi:snowflake";
const MORE_INFO_DIALOG = "ha-more-info-dialog";

// Below this viewport width the dialog stacks, as it does on a phone.
const SPLIT_FROM = 900;
// Home Assistant's dialog is 580px; this is what it widens to when split.
const SPLIT_DIALOG_WIDTH = 750;
const LIGHT_COLUMN_WIDTH = 320;

const STYLES = `
  .content { padding: 0 24px 24px; }
  .divider { height: 1px; background: rgba(var(--rgb-primary-text-color, 255,255,255), .08); margin: 8px 0 20px; }
  /* Side by side, the columns separate things; a rule across the top just looks odd. */
  .content.wide .divider { display: none; }
  /* Beside the light controls the left padding is the column gap, but the right edge is the
     dialog's, so it keeps the dialog's own padding. */
  .content.wide { padding: 0 24px 24px 0; }
  /* The speed has a host of its own; its padding would stack on the slider's own margin. */
  .content.flush { padding-bottom: 0; }

  .speed {
    /* Home Assistant's Effect button sits right above this; it needs room. */
    display: flex; align-items: center; gap: 12px; margin: 20px 0 24px; padding-right: 6px;
    font-size: 13px; color: var(--secondary-text-color);
  }
  .speed input[type="range"] { flex: 1; accent-color: var(--primary-color, #03a9f4); }
  .speed .value { min-width: 34px; text-align: right; font-variant-numeric: tabular-nums; }

  /* Segmented control, like Home Assistant's own mode buttons. */
  .tabs {
    display: flex; gap: 4px; margin-bottom: 20px; padding: 4px;
    border-radius: 999px; background: var(--seg-track);
  }
  .tab {
    flex: 1; padding: 9px 16px; border-radius: 999px; border: none; cursor: pointer;
    font-size: 14px; font-weight: 500; background: transparent; color: var(--secondary-text-color);
    transition: background .18s ease, color .18s ease;
  }
  .tab:hover:not(.active) { color: var(--primary-text-color); }
  .tab.active { background: var(--seg-active-bg); color: var(--seg-active-fg); box-shadow: 0 1px 3px rgba(0,0,0,.25); }

  .list { display: flex; flex-direction: column; gap: 6px; }
  .item { display: flex; align-items: stretch; gap: 2px; }
  .item .label {
    flex: 1; min-width: 0; padding: 12px; border-radius: 10px 0 0 10px; border: none; cursor: pointer;
    text-align: left; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    background: rgba(var(--rgb-primary-text-color, 255,255,255), .06); color: var(--primary-text-color);
  }
  .item .label.active { background: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff); }
  .item .star {
    width: 42px; border: none; border-radius: 0 10px 10px 0; cursor: pointer; --mdc-icon-size: 20px;
    display: grid; place-items: center;
    background: rgba(var(--rgb-primary-text-color, 255,255,255), .06); color: var(--secondary-text-color);
  }
  .item .star.on { color: #ffc107; }

  .eyebrow {
    font-size: 11px; font-weight: 500; letter-spacing: .06em; text-transform: uppercase;
    color: var(--secondary-text-color); margin: 0 0 6px 4px;
  }

  /* Our own folder menu: a native select's list is drawn by the browser and can't be styled. */
  .picker { position: relative; margin-bottom: 22px; }
  .picker-button {
    width: 100%; display: flex; align-items: center; gap: 8px; cursor: pointer;
    padding: 12px 14px; border-radius: 10px; font-size: 14px; text-align: left;
    background: rgba(var(--rgb-primary-text-color, 255,255,255), .06);
    color: var(--primary-text-color);
    border: 1px solid rgba(var(--rgb-primary-text-color, 255,255,255), .1);
  }
  .picker-button span { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .picker-button ha-icon { --mdc-icon-size: 20px; color: var(--secondary-text-color); }
  .picker-menu {
    position: absolute; top: calc(100% + 6px); left: 0; right: 0; z-index: 2;
    max-height: 320px; overflow: auto; padding: 8px; border-radius: 14px;
    background: var(--card-background-color, #1c1c1c);
    border: 1px solid rgba(var(--rgb-primary-text-color, 255,255,255), .1);
    box-shadow: 0 8px 24px rgba(0,0,0,.45);
  }
  .picker-menu[hidden] { display: none; }
  .picker-item {
    display: block; width: 100%; text-align: left; cursor: pointer; border: none;
    padding: 10px 12px; border-radius: 8px; font-size: 14px;
    background: transparent; color: var(--primary-text-color);
  }
  .picker-item:hover { background: rgba(var(--rgb-primary-text-color, 255,255,255), .08); }
  .picker-item.selected { color: var(--primary-color, #03a9f4); font-weight: 500; }

  .search { position: relative; margin-bottom: 10px; }
  .search ha-icon {
    position: absolute; left: 12px; top: 50%; transform: translateY(-50%);
    color: var(--secondary-text-color); --mdc-icon-size: 20px; pointer-events: none;
  }
  input[type="search"] {
    width: 100%; padding: 12px 12px 12px 40px; border-radius: 10px; font-size: 14px; box-sizing: border-box;
    background: rgba(var(--rgb-primary-text-color, 255,255,255), .06);
    color: var(--primary-text-color); border: 1px solid rgba(var(--rgb-primary-text-color, 255,255,255), .1);
  }
  input[type="search"]::placeholder { color: var(--secondary-text-color); }
  input[type="search"]::-webkit-search-cancel-button { margin-left: 8px; }

  .hint { color: var(--secondary-text-color); font-size: 12px; margin-top: 10px; }
  .empty { color: var(--secondary-text-color); font-size: 13px; padding: 8px 0; }
  .error {
    padding: 16px; border-radius: var(--ha-card-border-radius, 12px);
    background: var(--ha-card-background, var(--card-background-color, #1c1c1c));
    color: var(--secondary-text-color); font-size: 14px;
  }
`;

/** Favourites, as published by the integration. */
const favouritesOf = (light) => light.attributes.favourite_presets || [];

/** Escape text before putting it in markup: preset names come from the device. */
const esc = (value) =>
  String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

/** Find a descendant by tag name, crossing shadow roots. */
const deepFind = (node, localName, depth = 0) => {
  if (!node || depth > 6) return null;
  if (node.localName === localName) return node;
  for (const child of [...(node.shadowRoot?.children ?? []), ...(node.children ?? [])]) {
    const hit = deepFind(child, localName, depth + 1);
    if (hit) return hit;
  }
  return null;
};

class GoulyCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._tab = "favourites";
    this._search = "";
  }

  setConfig(config) {
    if (!config || !config.entity || !config.entity.startsWith("light.")) {
      throw new Error("Set `entity` to your Gouly light, e.g. light.christmas_lights_front");
    }
    this._config = config;
    this.shadowRoot.innerHTML = `<style>${STYLES}</style><div id="root"></div>`;
  }

  getCardSize() {
    return 1;
  }

  static getStubConfig(hass) {
    const light = Object.keys(hass.states).find((id) => id.startsWith("light."));
    return { type: "custom:gouly-card", entity: light || "light.gouly" };
  }

  set hass(hass) {
    this._hass = hass;
    this._renderRow();
    if (this._root) this._render();
  }

  // ---- entities -------------------------------------------------------------------

  get _light() {
    return this._hass?.states[this._config.entity];
  }

  _sibling(kind, key) {
    const configured = this._config[`${kind}_${key}`] || this._config[key];
    if (configured) return this._hass.states[configured];
    const entities = this._hass.entities || {};
    const deviceId = entities[this._config.entity]?.device_id;
    if (!deviceId) return undefined;
    const ids = Object.keys(entities).filter(
      (id) => id.startsWith(`${kind}.`) && entities[id].device_id === deviceId
    );
    // The translation key; failing that, the entity id ending the integration first gave it.
    const match =
      ids.find((id) => entities[id].platform === "gouly" && entities[id].translation_key === key) ||
      ids.find((id) => id.endsWith(`_${key}`));
    return match ? this._hass.states[match] : undefined;
  }

  get _folderSelect() { return this._sibling("select", "preset_folder"); }
  get _presetSelect() { return this._sibling("select", "preset"); }
  get _speed() { return this._sibling("number", "effect_speed"); }

  _call(domain, service, data) {
    this._hass.callService(domain, service, data);
  }

  // ---- the dashboard row ----------------------------------------------------------

  /** Home Assistant's own tile card, so the row matches the rest of the dashboard. */
  async _ensureTile() {
    if (this._tile || this._tilePending) return;
    this._tilePending = true;
    try {
      const helpers = await window.loadCardHelpers();
      const tile = helpers.createCardElement({
        type: "tile",
        entity: this._config.entity,
        icon: this._config.icon || DEFAULT_ICON,
        name: this._config.name,
        // The tile detects taps itself; fire-dom-event is how it tells us about one.
        tap_action: { action: "fire-dom-event", gouly: "open" },
        icon_tap_action: { action: "toggle" },
        hold_action: { action: "none" },
        double_tap_action: { action: "none" },
      });
      tile.hass = this._hass;
      tile.addEventListener("ll-custom", (event) => {
        if (event.detail?.gouly === "open") this._openDialog();
      });
      this._tile = tile;
      const root = this.shadowRoot.getElementById("root");
      root.innerHTML = "";
      root.appendChild(tile);
    } catch (error) {
      console.error("gouly-card: couldn't create the tile card", error);
      this.shadowRoot.getElementById("root").innerHTML =
        `<div class="error">Couldn't load Home Assistant's tile card.</div>`;
    } finally {
      this._tilePending = false;
    }
  }

  _renderRow() {
    if (!this._config || !this._hass) return;
    if (!this._tile) this._ensureTile();
    else this._tile.hass = this._hass;
  }

  // ---- Home Assistant's dialog, with our section added ----------------------------

  /** Open Home Assistant's own more-info dialog, then add our part to it. */
  _openDialog() {
    document.querySelector("home-assistant")?.dispatchEvent(
      new CustomEvent("hass-more-info", {
        detail: { entityId: this._config.entity },
        bubbles: true,
        composed: true,
      })
    );
    this._attach();
  }

  /** The dialog is built asynchronously, so look for it for a moment. */
  _attach(attempt = 0) {
    const dialog = document.querySelector("home-assistant")?.shadowRoot?.querySelector(MORE_INFO_DIALOG);
    const container = dialog?.shadowRoot?.querySelector(".content");
    if (!container) {
      if (attempt < 40) setTimeout(() => this._attach(attempt + 1), 50);
      else console.warn("gouly-card: couldn't find Home Assistant's dialog to add presets to");
      return;
    }
    if (container.querySelector(".gouly-extras")) return;

    // Two shadow roots: the speed belongs with the light controls, the rest is our section.
    this._speedRoot = this._makeHost(container, "gouly-speed", `<div id="speed"></div>`, "flush");
    this._presetsRoot = this._makeHost(
      container,
      "gouly-extras",
      `<div class="divider"></div><div class="tabs"></div><div id="tab-content"></div>`
    );
    this._root = this._presetsRoot;

    this._split(dialog, container);
    dialog.addEventListener("dialog-closed", () => this._detach(), { once: true });
    this._render();
  }

  _makeHost(container, className, inner, contentClass = "") {
    const host = document.createElement("div");
    host.className = className;
    const root = host.attachShadow({ mode: "open" });
    root.innerHTML = `<style>${STYLES}</style><div class="content ${contentClass}">${inner}</div>`;
    container.appendChild(host);
    return root;
  }

  /**
   * On a wide screen, lay the dialog out in two columns: Home Assistant's light controls and the
   * speed slider on the left, our presets on the right, in a wider dialog.
   *
   * The dialog belongs to Home Assistant and is reused for other entities, so everything changed
   * here is recorded and put back in _detach.
   */
  _split(dialog, container) {
    if (window.innerWidth < SPLIT_FROM) return;
    const info = container.querySelector("ha-more-info-info");
    if (!info) return;

    // Each column scrolls on its own: stretched to the container's height, they only get one
    // when the dialog has stopped growing, so a short dialog still behaves as it did. The column
    // is a flex column so the controls keep their own height inside it - given a definite one to
    // measure against they overflow their box and paint over the speed slider.
    const column = `min-width: 0; min-height: 0; overflow-y: auto;`;
    // Recorded before anything is changed: this dialog is Home Assistant's and gets reused.
    this._restore = {
      container: [container, container.getAttribute("style")],
      info: [info, info.getAttribute("style")],
    };
    const left = document.createElement("div");
    left.style.cssText = `flex: 0 0 ${LIGHT_COLUMN_WIDTH}px; display: flex; flex-direction: column; ${column}`;
    container.insertBefore(left, info);
    left.append(info, this._speedRoot.host);
    Object.assign(info.style, { flex: "0 0 auto", height: "auto", minHeight: "auto" });

    this._restore.left = left;
    Object.assign(container.style, {
      display: "flex",
      alignItems: "stretch",
      gap: "16px",
      minHeight: "0",
    });
    this._presetsRoot.host.style.cssText = `flex: 1; ${column}`;
    this._presetsRoot.querySelector(".content").classList.add("wide");

    // The sheet's width comes from a custom property on the Web Awesome dialog that Home
    // Assistant renders it in; setting a width on the elements themselves does nothing.
    const wa = deepFind(dialog, "wa-dialog");
    if (wa) {
      this._restore.wa = [wa, wa.getAttribute("style")];
      wa.style.setProperty("--width", `${SPLIT_DIALOG_WIDTH}px`);
    } else {
      console.warn("gouly-card: couldn't find the dialog element to widen");
    }
  }

  _detach() {
    const restore = this._restore;
    if (restore) {
      const [info] = restore.info;
      restore.container[0].insertBefore(info, restore.left);
      restore.left.remove();
      [restore.container, restore.info, restore.wa].forEach((entry) => {
        if (!entry) return;
        const [element, style] = entry;
        if (style === null) element.removeAttribute("style");
        else element.setAttribute("style", style);
      });
      this._restore = null;
    }
    this._speedRoot?.host?.remove();
    this._presetsRoot?.host?.remove();
    this._speedRoot = this._presetsRoot = this._root = null;
    this._signatureCache = null;
  }

  _render() {
    if (!this._root || !this._light) return;
    this._applyTheme();
    this._renderSpeed();
    this._renderTabs();
  }

  /** The segmented control's colours, which differ between light and dark themes. */
  _applyTheme() {
    const background = getComputedStyle(document.documentElement)
      .getPropertyValue("--card-background-color")
      .trim();
    const [r, g, b] = (background.match(/\d+(\.\d+)?/g) || []).map(Number);
    const dark =
      [r, g, b].some((value) => value === undefined)
        ? window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? true
        : (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 < 0.5;
    const content = this._root.querySelector(".content");
    content.style.setProperty("--seg-track", dark ? "rgba(255, 255, 255, .08)" : "rgba(0, 0, 0, .06)");
    content.style.setProperty("--seg-active-bg", dark ? "rgba(255, 255, 255, .92)" : "#fff");
    content.style.setProperty("--seg-active-fg", "#1c1c1e");
  }

  _renderSpeed() {
    const speed = this._speed;
    const container = this._speedRoot?.querySelector("#speed");
    if (!container) return;
    if (!speed) {
      container.innerHTML = "";
      return;
    }
    if (container.dataset.value === speed.state) return; // don't fight a slider being dragged
    container.dataset.value = speed.state;
    container.innerHTML = `
      <div class="speed">
        <span>Effect speed</span>
        <input type="range" id="speed-input" min="1" max="255" value="${esc(speed.state)}">
        <span class="value">${esc(speed.state)}</span>
      </div>`;
    container.querySelector("#speed-input").addEventListener("change", (event) =>
      this._call("number", "set_value", { entity_id: speed.entity_id, value: Number(event.target.value) })
    );
  }

  // ---- favourites and presets -----------------------------------------------------

  _renderTabs() {
    const tabs = this._root.querySelector(".tabs");
    if (tabs.dataset.tab !== this._tab) {
      tabs.dataset.tab = this._tab;
      tabs.innerHTML = [
        ["favourites", "Favourites"],
        ["presets", "Presets"],
      ]
        .map(([tab, label]) => `<button class="tab ${this._tab === tab ? "active" : ""}" data-tab="${tab}">${label}</button>`)
        .join("");
      tabs.querySelectorAll(".tab").forEach((tab) =>
        tab.addEventListener("click", () => {
          this._tab = tab.dataset.tab;
          this._search = "";
          this._render();
        })
      );
    }

    // Only rebuild the list when what it shows has changed, so an open menu or a half typed
    // search isn't thrown away by an unrelated state update.
    const { list, favourites } = this._signature();
    const previous = this._signatureCache;
    if (previous && previous.list === list && previous.favourites === favourites) return;
    this._signatureCache = { list, favourites };

    // Starring a preset only changes its star. Swapping those in place keeps a long list from
    // being rebuilt - and scrolled back to the top - every time one is tapped.
    if (previous && previous.list === list && this._tab === "presets") {
      this._refreshStars();
      return;
    }

    const content = this._root.querySelector("#tab-content");
    const active = content.querySelector("input[type=search]");
    const caret =
      active && active === this._root.activeElement ? [active.selectionStart, active.selectionEnd] : null;
    content.innerHTML = this._tabMarkup();
    this._wire();
    if (caret) {
      const search = content.querySelector("input[type=search]");
      search?.focus();
      search?.setSelectionRange(caret[0], caret[1]);
    }
  }

  /** What the list is showing, with the favourites kept apart so stars can be updated alone. */
  _signature() {
    const folders = this._folderSelect;
    const presets = this._presetSelect;
    return {
      list: JSON.stringify([
        this._tab,
        this._search,
        // On the Favourites tab the favourites are the list, so they belong in the signature.
        this._tab === "favourites" ? favouritesOf(this._light) : null,
        folders?.state,
        folders?.attributes.options?.length,
        presets?.state,
        presets?.attributes.options,
      ]),
      favourites: JSON.stringify(favouritesOf(this._light)),
    };
  }

  /** Bring the stars in the rendered list up to date without touching anything else. */
  _refreshStars() {
    const favourites = new Set(favouritesOf(this._light));
    this._root.querySelectorAll("[data-star]").forEach((star) => {
      const starred = favourites.has(star.dataset.star);
      star.classList.toggle("on", starred);
      star.title = starred ? "Remove from favourites" : "Add to favourites";
      star.querySelector("ha-icon")?.setAttribute("icon", starred ? "mdi:star" : "mdi:star-outline");
    });
  }

  _tabMarkup() {
    if (this._tab === "favourites") {
      const favourites = [...favouritesOf(this._light)].sort((a, b) => a.localeCompare(b));
      if (!favourites.length) {
        return `<div class="empty">No favourites yet. Open <b>Presets</b> and tap the star on one.</div>`;
      }
      return `<div class="list">${favourites
        .map(
          (preset) => `
          <div class="item">
            <button class="label" data-favourite="${esc(preset)}">${esc(preset)}</button>
            <button class="star on" data-star="${esc(preset)}" title="Remove from favourites">
              <ha-icon icon="mdi:star"></ha-icon>
            </button>
          </div>`
        )
        .join("")}</div>`;
    }

    const folders = this._folderSelect;
    const presets = this._presetSelect;
    if (!folders || !presets) {
      return `<div class="empty">No preset library installed. Add <b>gouly_presets.json</b> in the integration's Configure screen.</div>`;
    }

    const selected = presets.state && !["unknown", "unavailable"].includes(presets.state) ? presets.state : null;
    const options = presets.attributes.options || [];
    const matches = options.filter((option) => option.toLowerCase().includes(this._search.toLowerCase()));
    const favourites = new Set(favouritesOf(this._light));
    return `
      <div class="eyebrow">Preset folder</div>
      <div class="picker">
        <button class="picker-button" id="folder-button">
          <span>${esc(
            ["unknown", "unavailable"].includes(folders.state) ? "Choose a folder" : folders.state
          )}</span>
          <ha-icon icon="mdi:chevron-down"></ha-icon>
        </button>
        <div class="picker-menu" id="folder-menu" hidden>
          ${(folders.attributes.options || [])
            .map(
              (option) =>
                `<button class="picker-item ${option === folders.state ? "selected" : ""}" data-folder="${esc(
                  option
                )}">${esc(option)}</button>`
            )
            .join("")}
        </div>
      </div>
      <div class="search">
        <ha-icon icon="mdi:magnify"></ha-icon>
        <input type="search" id="search" placeholder="Search ${options.length} presets" value="${esc(this._search)}">
      </div>
      ${
        matches.length
          ? `<div class="list">${matches
              .map((option) => {
                const preset = `${folders.state} / ${option}`;
                const starred = favourites.has(preset);
                return `
                  <div class="item">
                    <button class="label ${option === selected ? "active" : ""}" data-preset="${esc(option)}">${esc(
                  option
                )}</button>
                    <button class="star ${starred ? "on" : ""}" data-star="${esc(
                  preset
                )}" title="${starred ? "Remove from favourites" : "Add to favourites"}">
                      <ha-icon icon="${starred ? "mdi:star" : "mdi:star-outline"}"></ha-icon>
                    </button>
                  </div>`;
              })
              .join("")}</div>
             <div class="hint">Tap a preset to run it, the star to keep it in Favourites.</div>`
          : `<div class="empty">No presets match.</div>`
      }`;
  }

  _wire() {
    const root = this._root;
    const button = root.querySelector("#folder-button");
    const menu = root.querySelector("#folder-menu");
    if (button && menu) {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        menu.hidden = !menu.hidden;
        if (!menu.hidden) menu.querySelector(".selected")?.scrollIntoView({ block: "center" });
      });
      root.querySelector(".content").addEventListener("click", () => {
        menu.hidden = true;
      });
    }
    root.querySelector("#search")?.addEventListener("input", (event) => {
      this._search = event.target.value;
      // Replace just the list, so focus and caret stay put while typing.
      const list = root.querySelector(".list, .empty");
      const markup = document.createElement("div");
      markup.innerHTML = this._tabMarkup();
      const replacement = markup.querySelector(".list, .empty");
      if (list && replacement) {
        this._signatureCache = this._signature();
        list.replaceWith(replacement);
        this._wireItems();
      }
    });
    this._wireItems();
  }

  _wireItems() {
    const root = this._root;
    const on = (selector, handler) =>
      root.querySelectorAll(selector).forEach((item) => item.addEventListener("click", () => handler(item)));

    on("[data-favourite]", (item) =>
      this._call("gouly", "apply_preset", { entity_id: this._config.entity, preset: item.dataset.favourite })
    );
    on("[data-preset]", (item) =>
      this._call("select", "select_option", {
        entity_id: this._presetSelect.entity_id,
        option: item.dataset.preset,
      })
    );
    on("[data-folder]", (item) => {
      this._search = "";
      this._call("select", "select_option", {
        entity_id: this._folderSelect.entity_id,
        option: item.dataset.folder,
      });
    });
    // One handler for both: which way it goes depends on the favourites as they are now, not as
    // they were when the button was drawn.
    on("[data-star]", (item) => {
      const preset = item.dataset.star;
      const starred = favouritesOf(this._light).includes(preset);
      this._call("gouly", starred ? "remove_favourite" : "add_favourite", {
        entity_id: this._config.entity,
        preset,
      });
    });
  }
}

customElements.define("gouly-card", GoulyCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "gouly-card",
  name: "Gouly Light",
  description: "A Gouly light with its presets and favourites in Home Assistant's own dialog.",
  preview: false,
  documentationURL: "https://github.com/mikemaat/ha-gouly#the-gouly-card",
});

console.info(`%c GOULY-CARD %c ${VERSION} `, "color:#fff;background:#03a9f4;font-weight:700", "color:#03a9f4;background:#fff");

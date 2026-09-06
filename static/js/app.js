/* HCG Knowledge Centre - shared behaviour. No framework, no build step.
   Exposes window.HKC with: theme, dialog, confirm, prompt, toast, menu, tabs, filter,
   pagination, escapeHtml, fetchJSON, markRead, notifications. */
(function () {
  'use strict';
  const HKC = (window.HKC = window.HKC || {});
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const html = document.documentElement;

  const reduceMotion = () =>
    html.dataset.motion === 'reduce' || window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function afterAnimation(el, done, fallback = 420) {
    let finished = false;
    const finish = () => { if (finished) return; finished = true; el.removeEventListener('animationend', finish); el.removeEventListener('transitionend', finish); done(); };
    el.addEventListener('animationend', finish, { once: true });
    el.addEventListener('transitionend', finish, { once: true });
    setTimeout(finish, reduceMotion() ? 60 : fallback);
  }

  // ------------------------------------------------------------------ utilities
  HKC.escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  HKC.csrf = () => (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  HKC.fetchJSON = async (url, options = {}) => {
    const headers = Object.assign({ 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest', 'X-CSRF-Token': HKC.csrf() }, options.headers || {});
    const response = await fetch(url, Object.assign({}, options, { headers }));
    let data = null;
    try { data = await response.json(); } catch (e) { /* not JSON */ }
    return { ok: response.ok, status: response.status, data };
  };
  const focusables = (root) => $$('a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])', root).filter((el) => el.offsetParent !== null || el === document.activeElement);

  // ------------------------------------------------------------------ dev hooks (?motion=reduce&transparency=reduce&contrast=more)
  (function devHooks() {
    const params = new URLSearchParams(location.search);
    for (const key of ['motion', 'transparency', 'contrast']) {
      if (params.has(key)) html.dataset[key] = params.get(key);
    }
  })();

  // ------------------------------------------------------------------ theme
  const THEME_KEY = 'hkc-theme';
  HKC.theme = {
    get() {
      try {
        const stored = localStorage.getItem(THEME_KEY) || localStorage.getItem('learnly-theme');
        if (stored === 'dark' || stored === 'light') return stored;
      } catch (e) { /* storage unavailable */ }
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    },
    apply(mode, animate) {
      if (animate && !reduceMotion()) {
        html.classList.add('theme-transition');
        setTimeout(() => html.classList.remove('theme-transition'), 320);
      }
      html.classList.toggle('dark', mode === 'dark');
      const meta = $('meta[name="theme-color"]:not([media])');
      if (meta) meta.setAttribute('content', mode === 'dark' ? '#111114' : '#f5f5f7');
      $$('[data-theme-toggle]').forEach((btn) => {
        btn.setAttribute('aria-pressed', String(mode === 'dark'));
        btn.setAttribute('aria-label', mode === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
      });
      document.dispatchEvent(new CustomEvent('hkc:themechange', { detail: { theme: mode } }));
    },
    set(mode) {
      try { localStorage.setItem(THEME_KEY, mode); localStorage.removeItem('learnly-theme'); } catch (e) { /* ignore */ }
      this.apply(mode, true);
    },
    toggle() { this.set(html.classList.contains('dark') ? 'light' : 'dark'); },
  };

  // ------------------------------------------------------------------ dialogs (<dialog> based: sheets, drawer, confirm)
  const openDialogs = new Set();
  HKC.dialog = {
    open(el, opener) {
      if (!el || el.open) return;
      el.__opener = opener || document.activeElement;
      el.classList.remove('is-closing');
      if (typeof el.showModal === 'function') el.showModal(); else el.setAttribute('open', '');
      openDialogs.add(el);
      document.body.dataset.modalOpen = '';
      const target = $('[autofocus]', el) || focusables(el)[0];
      if (target) target.focus({ preventScroll: true });
      el.dispatchEvent(new CustomEvent('hkc:open'));
    },
    close(el, returnValue) {
      if (!el || !el.open || el.classList.contains('is-closing')) return;
      el.classList.add('is-closing');
      afterAnimation(el, () => {
        el.classList.remove('is-closing');
        if (typeof el.close === 'function') el.close(returnValue); else el.removeAttribute('open');
        openDialogs.delete(el);
        if (openDialogs.size === 0) delete document.body.dataset.modalOpen;
        const opener = el.__opener;
        if (opener && typeof opener.focus === 'function' && document.contains(opener)) opener.focus({ preventScroll: true });
        el.dispatchEvent(new CustomEvent('hkc:close', { detail: { returnValue } }));
      }, 320);
    },
    closeAll() { openDialogs.forEach((el) => this.close(el)); },
  };
  function wireDialog(el) {
    if (el.__wired) return;
    el.__wired = true;
    el.addEventListener('cancel', (event) => { event.preventDefault(); HKC.dialog.close(el, 'cancel'); });
    el.addEventListener('click', (event) => {
      if (event.target === el) HKC.dialog.close(el, 'backdrop'); // click on the backdrop (outside the content)
    });
    $$('[data-dialog-close]', el).forEach((btn) => btn.addEventListener('click', () => HKC.dialog.close(el, btn.dataset.dialogClose || 'close')));
  }

  // ------------------------------------------------------------------ confirm / prompt (replace native dialogs)
  function buildSheet(kind, options) {
    const el = document.createElement('dialog');
    el.className = 'sheet sheet-sm';
    el.setAttribute('aria-labelledby', 'hkc-dialog-title');
    const danger = options.danger ? 'btn-danger' : 'btn-primary';
    el.innerHTML = `
      <form method="dialog" class="sheet-form">
        <div class="sheet-header"><h2 id="hkc-dialog-title" class="text-lg">${HKC.escapeHtml(options.title || (kind === 'prompt' ? 'Enter a value' : 'Are you sure?'))}</h2></div>
        <div class="sheet-body">
          ${options.body ? `<p class="text-fg-2">${HKC.escapeHtml(options.body)}</p>` : ''}
          ${kind === 'prompt' ? `<label class="field"><span class="field-label">${HKC.escapeHtml(options.label || 'Value')}</span><input class="input" name="value" autofocus value="${HKC.escapeHtml(options.value || '')}" placeholder="${HKC.escapeHtml(options.placeholder || '')}"></label>` : ''}
        </div>
        <div class="sheet-footer">
          <button type="button" class="btn btn-secondary" data-dialog-close="cancel">${HKC.escapeHtml(options.cancelLabel || 'Cancel')}</button>
          <button type="submit" class="btn ${danger}" value="ok">${HKC.escapeHtml(options.confirmLabel || (kind === 'prompt' ? 'Save' : 'Confirm'))}</button>
        </div>
      </form>`;
    document.body.appendChild(el);
    wireDialog(el);
    return el;
  }
  HKC.confirm = (options = {}) => new Promise((resolve) => {
    const el = buildSheet('confirm', options);
    $('form', el).addEventListener('submit', (event) => { event.preventDefault(); HKC.dialog.close(el, 'ok'); });
    el.addEventListener('hkc:close', (event) => { resolve(event.detail.returnValue === 'ok'); el.remove(); });
    HKC.dialog.open(el);
  });
  HKC.prompt = (options = {}) => new Promise((resolve) => {
    const el = buildSheet('prompt', options);
    const input = $('input[name="value"]', el);
    $('form', el).addEventListener('submit', (event) => { event.preventDefault(); HKC.dialog.close(el, 'ok'); });
    el.addEventListener('hkc:close', (event) => { resolve(event.detail.returnValue === 'ok' ? input.value.trim() : null); el.remove(); });
    HKC.dialog.open(el);
  });

  // ------------------------------------------------------------------ menus / popovers
  let openMenu = null;
  function closeMenu(menu) {
    if (!menu || !menu.classList.contains('is-open')) return;
    const trigger = menu.__trigger;
    menu.classList.add('is-closing');
    menu.classList.remove('is-open');
    if (trigger) trigger.setAttribute('aria-expanded', 'false');
    afterAnimation(menu, () => { menu.classList.remove('is-closing'); menu.hidden = true; }, 200);
    if (openMenu === menu) openMenu = null;
  }
  function openMenuFor(trigger) {
    const menu = document.getElementById(trigger.getAttribute('aria-controls'));
    if (!menu) return;
    if (openMenu && openMenu !== menu) closeMenu(openMenu);
    menu.__trigger = trigger;
    menu.hidden = false;
    requestAnimationFrame(() => menu.classList.add('is-open'));
    trigger.setAttribute('aria-expanded', 'true');
    openMenu = menu;
    const first = $('[role="menuitem"], a, button', menu);
    if (first && menu.getAttribute('role') === 'menu') first.focus();
    menu.dispatchEvent(new CustomEvent('hkc:menuopen'));
  }
  HKC.menu = { close: () => closeMenu(openMenu) };
  document.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-menu]');
    if (trigger) {
      event.preventDefault();
      const menu = document.getElementById(trigger.getAttribute('aria-controls'));
      if (menu && menu.classList.contains('is-open')) closeMenu(menu); else openMenuFor(trigger);
      return;
    }
    if (openMenu && !openMenu.contains(event.target)) closeMenu(openMenu);
  });
  document.addEventListener('keydown', (event) => {
    if (!openMenu) return;
    const items = $$('[role="menuitem"], a, button', openMenu).filter((el) => !el.hidden);
    const index = items.indexOf(document.activeElement);
    if (event.key === 'Escape') { const trigger = openMenu.__trigger; closeMenu(openMenu); if (trigger) trigger.focus(); }
    else if (event.key === 'ArrowDown') { event.preventDefault(); (items[index + 1] || items[0])?.focus(); }
    else if (event.key === 'ArrowUp') { event.preventDefault(); (items[index - 1] || items[items.length - 1])?.focus(); }
    else if (event.key === 'Home') { event.preventDefault(); items[0]?.focus(); }
    else if (event.key === 'End') { event.preventDefault(); items[items.length - 1]?.focus(); }
    else if (event.key === 'Tab') { closeMenu(openMenu); }
  });

  // ------------------------------------------------------------------ tabs
  function wireTabs(root) {
    const tabs = $$('[role="tab"]', root);
    const panels = tabs.map((tab) => document.getElementById(tab.getAttribute('aria-controls'))).filter(Boolean);
    const select = (tab, focus) => {
      tabs.forEach((t) => { const on = t === tab; t.setAttribute('aria-selected', String(on)); t.tabIndex = on ? 0 : -1; });
      panels.forEach((p) => {
        const on = p.id === tab.getAttribute('aria-controls');
        if (on && p.hidden) { p.hidden = false; p.classList.add('is-entering'); setTimeout(() => p.classList.remove('is-entering'), 200); }
        else if (!on) p.hidden = true;
      });
      if (focus) tab.focus();
      if (root.dataset.tabsHash !== undefined) history.replaceState(null, '', '#' + tab.getAttribute('aria-controls'));
      root.dispatchEvent(new CustomEvent('hkc:tabchange', { detail: { tab } }));
    };
    tabs.forEach((tab) => {
      tab.addEventListener('click', () => select(tab, false));
      tab.addEventListener('keydown', (event) => {
        const i = tabs.indexOf(tab);
        const map = { ArrowRight: tabs[(i + 1) % tabs.length], ArrowLeft: tabs[(i - 1 + tabs.length) % tabs.length], Home: tabs[0], End: tabs[tabs.length - 1] };
        if (map[event.key]) { event.preventDefault(); select(map[event.key], true); }
      });
    });
    const fromHash = root.dataset.tabsHash !== undefined && location.hash && tabs.find((t) => '#' + t.getAttribute('aria-controls') === location.hash);
    select(fromHash || tabs.find((t) => t.getAttribute('aria-selected') === 'true') || tabs[0], false);
  }
  HKC.tabs = { wire: wireTabs };

  // ------------------------------------------------------------------ toasts
  function region() {
    let el = document.getElementById('toast-region');
    if (!el) { el = document.createElement('div'); el.id = 'toast-region'; el.className = 'toast-region'; el.setAttribute('role', 'status'); el.setAttribute('aria-live', 'polite'); document.body.appendChild(el); }
    return el;
  }
  function dismissToast(toast) {
    if (!toast || toast.classList.contains('is-leaving')) return;
    toast.classList.add('is-leaving');
    afterAnimation(toast, () => toast.remove(), 250);
  }
  function armToast(toast, timeout) {
    let timer = null;
    const start = () => { if (timeout > 0) timer = setTimeout(() => dismissToast(toast), timeout); };
    const stop = () => { if (timer) clearTimeout(timer); timer = null; };
    toast.addEventListener('mouseenter', stop); toast.addEventListener('mouseleave', start);
    toast.addEventListener('focusin', stop); toast.addEventListener('focusout', start);
    $$('.toast-close', toast).forEach((btn) => btn.addEventListener('click', () => dismissToast(toast)));
    start();
    const all = $$('.toast', region());
    if (all.length > 3) dismissToast(all[0]);
  }
  HKC.toast = (message, kind = 'info', options = {}) => {
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.dataset.kind = kind;
    if (kind === 'error') toast.setAttribute('role', 'alert');
    toast.innerHTML = `<div class="toast-body">${HKC.escapeHtml(message)}${options.action ? ` <button type="button" class="toast-action">${HKC.escapeHtml(options.action.label)}</button>` : ''}</div><button type="button" class="toast-close" aria-label="Dismiss"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 18L18 6M6 6l12 12"/></svg></button>`;
    if (options.action) $('.toast-action', toast).addEventListener('click', () => { options.action.onClick(); dismissToast(toast); });
    region().appendChild(toast);
    armToast(toast, options.timeout === undefined ? 5000 : options.timeout);
    return toast;
  };

  // ------------------------------------------------------------------ client-side filtering
  function wireFilter(root) {
    const input = $('[data-filter-input]', root);
    const chips = $$('[data-filter-chip]', root);
    const items = $$('[data-filter-item]', root);
    const empty = $('[data-filter-empty]', root);
    const state = {};
    const apply = () => {
      const q = (input ? input.value : '').trim().toLowerCase();
      let visible = 0;
      items.forEach((item) => {
        const text = (item.dataset.search || item.textContent || '').toLowerCase();
        let show = !q || text.includes(q);
        for (const key in state) { if (state[key] && state[key] !== 'all' && (item.dataset[key] || '').toLowerCase() !== state[key].toLowerCase()) show = false; }
        item.hidden = !show;
        if (show) visible += 1;
      });
      if (empty) empty.hidden = visible !== 0;
      root.dispatchEvent(new CustomEvent('hkc:filter', { detail: { visible } }));
    };
    if (input) input.addEventListener('input', apply);
    chips.forEach((chip) => {
      const key = chip.dataset.filterKey || 'filter';
      if (chip.getAttribute('aria-pressed') === 'true') state[key] = chip.dataset.filterValue;
      chip.addEventListener('click', () => {
        chips.filter((c) => (c.dataset.filterKey || 'filter') === key).forEach((c) => c.setAttribute('aria-pressed', 'false'));
        chip.setAttribute('aria-pressed', 'true');
        state[key] = chip.dataset.filterValue;
        apply();
      });
    });
    apply();
  }
  HKC.filter = { wire: wireFilter };

  // ------------------------------------------------------------------ pagination
  HKC.pagination = (container, state, onPage) => {
    const total = Math.max(1, state.totalPages || 1);
    const page = Math.min(Math.max(1, state.page || 1), total);
    const btn = (label, target, extra = '') => `<button type="button" class="btn btn-secondary btn-sm ${extra}" data-page="${target}" ${target < 1 || target > total || target === page ? 'disabled' : ''}>${label}</button>`;
    container.innerHTML = `<nav class="flex items-center justify-between gap-3" aria-label="Pagination"><span class="caption tabular">Page ${page} of ${total}</span><div class="flex gap-2">${btn('Previous', page - 1)}${btn('Next', page + 1)}</div></nav>`;
    $$('[data-page]', container).forEach((b) => b.addEventListener('click', () => onPage(Number(b.dataset.page))));
  };

  // ------------------------------------------------------------------ notifications (header bell + notifications page)
  HKC.markRead = (id, targetUrl) => fetch('/api/notifications/' + id + '/read', { method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRF-Token': HKC.csrf() } })
    .catch(() => null)
    .then(() => { if (targetUrl && targetUrl !== '#') window.location.href = targetUrl; else window.location.reload(); });
  window.markRead = HKC.markRead; // notifications.html still calls the global
  function wireNotifications() {
    const list = document.getElementById('notification-list');
    if (!list) return;
    const dot = document.getElementById('notification-badge');
    const countText = document.getElementById('notification-count-text');
    const bell = document.getElementById('notification-btn');
    let highestSeen = 0, initial = true;
    const sessionNew = new Set();
    function chime() {
      if (reduceMotion()) return;
      try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = ctx.createOscillator(); const gain = ctx.createGain();
        osc.connect(gain); gain.connect(ctx.destination); osc.type = 'sine';
        osc.frequency.setValueAtTime(880, ctx.currentTime); osc.frequency.exponentialRampToValueAtTime(440, ctx.currentTime + .5);
        gain.gain.setValueAtTime(.15, ctx.currentTime); gain.gain.exponentialRampToValueAtTime(.01, ctx.currentTime + .5);
        osc.start(); osc.stop(ctx.currentTime + .5);
      } catch (e) { /* audio blocked */ }
    }
    async function poll() {
      const { ok, data } = await HKC.fetchJSON('/api/notifications/unread');
      if (!ok || !data) return;
      let hasNew = false;
      (data.notifications || []).forEach((n) => {
        if (n.id > highestSeen) { if (!initial) { hasNew = true; sessionNew.add(n.id); } highestSeen = n.id; }
      });
      initial = false;
      if (hasNew) chime();
      const count = data.count || 0;
      if (dot) dot.hidden = count === 0;
      if (countText) { countText.hidden = count === 0; countText.textContent = count + ' new'; }
      if (bell) bell.setAttribute('aria-label', count ? `Notifications, ${count} unread` : 'Notifications');
      if (count === 0) { list.innerHTML = '<div class="empty" style="padding:1.5rem"><p class="caption">No new notifications.</p></div>'; return; }
      list.innerHTML = (data.notifications || []).map((n) => `
        <button type="button" class="menu-item ${sessionNew.has(n.id) ? 'is-new' : ''}" role="menuitem" data-mark-read="${n.id}" data-url="${HKC.escapeHtml(n.target_url || '#')}" style="display:block">
          <span class="block text-sm">${HKC.escapeHtml(n.message)}</span>
          <span class="block caption mt-1">${HKC.escapeHtml(new Date(n.created_at).toLocaleString())}</span>
        </button>`).join('');
    }
    poll();
    setInterval(poll, 30000);
  }
  document.addEventListener('click', (event) => {
    const el = event.target.closest('[data-mark-read]');
    if (!el) return;
    event.preventDefault();
    HKC.markRead(el.dataset.markRead, el.dataset.url);
  });

  // ------------------------------------------------------------------ release notes badge (seen state)
  function wireRelease() {
    const badge = $('[data-release-version]');
    if (!badge) return;
    const version = badge.dataset.releaseVersion;
    const dot = $('[data-release-dot]');
    try { if (dot) dot.hidden = localStorage.getItem('hkc-seen-version') === version; } catch (e) { /* ignore */ }
    const sheet = document.getElementById('release-sheet');
    if (sheet) sheet.addEventListener('hkc:open', () => { try { localStorage.setItem('hkc-seen-version', version); } catch (e) { /* ignore */ } if (dot) dot.hidden = true; });
  }

  // ------------------------------------------------------------------ boot
  function init() {
    HKC.theme.apply(HKC.theme.get(), false);
    $$('[data-theme-toggle]').forEach((btn) => btn.addEventListener('click', () => HKC.theme.toggle()));
    $$('dialog').forEach(wireDialog);
    document.addEventListener('click', (event) => {
      const opener = event.target.closest('[data-dialog-open]');
      if (!opener) return;
      const el = document.getElementById(opener.dataset.dialogOpen);
      if (el) { event.preventDefault(); wireDialog(el); HKC.dialog.open(el, opener); }
    });
    document.addEventListener('submit', (event) => {
      const form = event.target;
      if (!(form instanceof HTMLFormElement) || !form.dataset.confirm || form.__confirmed) return;
      event.preventDefault();
      HKC.confirm({ title: form.dataset.confirmTitle || 'Please confirm', body: form.dataset.confirm, confirmLabel: form.dataset.confirmLabel || 'Confirm', danger: form.dataset.confirmDanger !== undefined })
        .then((ok) => { if (ok) { form.__confirmed = true; form.requestSubmit ? form.requestSubmit() : form.submit(); } });
    });
    $$('[data-tabs]').forEach(wireTabs);
    $$('[data-filter]').forEach(wireFilter);
    $$('#toast-region .toast').forEach((toast) => armToast(toast, Number(toast.dataset.timeout || 5000)));
    const sentinel = document.getElementById('scroll-sentinel');
    const toolbar = $('.material-toolbar');
    if (sentinel && toolbar && 'IntersectionObserver' in window) {
      new IntersectionObserver(([entry]) => { toolbar.toggleAttribute('data-scrolled', !entry.isIntersecting); }, { threshold: 0 }).observe(sentinel);
    }
    wireNotifications();
    wireRelease();
    document.dispatchEvent(new CustomEvent('hkc:ready'));
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();

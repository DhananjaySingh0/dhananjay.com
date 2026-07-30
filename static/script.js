/* =========================================================================
   Portfolio front-end
   Loaded with `defer`, so the DOM is ready by the time this runs.
   ========================================================================= */
(function () {
  'use strict';

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  /* ---------------------------------------------------------------------
     Footer year
     Optional-chained: a page without #year must not kill the whole script,
     which is exactly what the old unguarded call did.
     --------------------------------------------------------------------- */
  const yearEl = document.getElementById('year');
  if (yearEl) yearEl.textContent = new Date().getFullYear();

  /* ---------------------------------------------------------------------
     Back to top
     --------------------------------------------------------------------- */
  document.getElementById('backToTop')?.addEventListener('click', () => {
    window.scrollTo({ top: 0, behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
  });

  function prefersReducedMotion() {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  /* ---------------------------------------------------------------------
     Navbar scroll state
     --------------------------------------------------------------------- */
  const siteNavbar = $('.navbar');
  if (siteNavbar) {
    let ticking = false;
    const update = () => {
      siteNavbar.classList.toggle('is-scrolled', window.scrollY > 12);
      ticking = false;
    };
    window.addEventListener('scroll', () => {
      if (!ticking) { ticking = true; requestAnimationFrame(update); }
    }, { passive: true });
    update();
  }

  /* ---------------------------------------------------------------------
     Theme toggle
     The initial theme is applied by an inline script in <head> so there is
     no flash. This only handles the click and keeps the label accurate.
     --------------------------------------------------------------------- */
  const root = document.documentElement;
  const themeToggle = document.getElementById('themeToggle');

  function syncThemeLabel() {
    if (!themeToggle) return;
    const isDark = root.getAttribute('data-theme') === 'dark';
    themeToggle.setAttribute('aria-label', isDark ? 'Switch to light mode' : 'Switch to dark mode');
    themeToggle.setAttribute('aria-pressed', String(!isDark));
  }
  syncThemeLabel();

  themeToggle?.addEventListener('click', () => {
    const next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem('theme', next); } catch (e) { /* private mode */ }
    syncThemeLabel();
  });

  /* ---------------------------------------------------------------------
     Mobile nav
     --------------------------------------------------------------------- */
  const burger = document.getElementById('burger');
  const navLinks = document.getElementById('navLinks');

  function setNavOpen(open) {
    if (!navLinks || !burger) return;
    navLinks.classList.toggle('open', open);
    burger.classList.toggle('active', open);
    burger.setAttribute('aria-expanded', String(open));
    burger.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
    document.body.classList.toggle('nav-open', open);
  }

  burger?.addEventListener('click', () => {
    setNavOpen(!navLinks.classList.contains('open'));
  });
  navLinks?.querySelectorAll('a').forEach((a) => {
    a.addEventListener('click', () => setNavOpen(false));
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && navLinks?.classList.contains('open')) {
      setNavOpen(false);
      burger?.focus();
    }
  });

  /* ---------------------------------------------------------------------
     Active nav link
     Rewritten as an IntersectionObserver. The old version read
     sec.offsetTop on every scroll event (layout thrash, non-passive) and
     compared `href === '#' + id`, which never matched on the contact page
     because those links are absolute ("/#about").
     --------------------------------------------------------------------- */
  const sections = $$('section[id]');
  const navAnchors = $$('.nav-links a');

  function hashOf(anchor) {
    const href = anchor.getAttribute('href') || '';
    const i = href.indexOf('#');
    return i === -1 ? '' : href.slice(i + 1);
  }

  if (sections.length && navAnchors.length && 'IntersectionObserver' in window) {
    let visible = new Map();
    const navObserver = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) visible.set(entry.target.id, entry.intersectionRatio);
        else visible.delete(entry.target.id);
      });
      let best = null, bestRatio = 0;
      visible.forEach((ratio, id) => { if (ratio > bestRatio) { bestRatio = ratio; best = id; } });
      if (!best) return;
      navAnchors.forEach((a) => a.classList.toggle('active', hashOf(a) === best));
    }, { rootMargin: '-45% 0px -45% 0px', threshold: [0, 0.25, 0.5, 1] });
    sections.forEach((s) => navObserver.observe(s));
  }

  /* ---------------------------------------------------------------------
     Animated stat counters
     Suffix now comes from data-suffix instead of being guessed from the
     value (the old `target === 100 ? '%' : '+'` turned "100+ projects"
     into "100%").
     --------------------------------------------------------------------- */
  const statEls = $$('[data-count]');
  if (statEls.length) {
    const counted = new WeakSet();
    const counterObserver = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting && !counted.has(entry.target)) {
          counted.add(entry.target);
          animateCount(entry.target);
        }
      });
    }, { threshold: 0.4 });
    statEls.forEach((el) => counterObserver.observe(el));
  }

  function animateCount(el) {
    const target = parseInt(el.dataset.count, 10);
    if (Number.isNaN(target)) return;
    const suffix = el.dataset.suffix ?? '+';
    if (prefersReducedMotion()) { el.textContent = target + suffix; return; }
    const duration = 1200;
    const start = performance.now();
    (function tick(now) {
      const progress = Math.min((now - start) / duration, 1);
      el.textContent = Math.floor(progress * target) + (progress === 1 ? suffix : '');
      if (progress < 1) requestAnimationFrame(tick);
    })(performance.now());
  }

  /* ---------------------------------------------------------------------
     Helpers
     --------------------------------------------------------------------- */
  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str ?? '';
    return div.innerHTML;
  }

  // Only emit hrefs a browser can safely follow. Mirrors safe_url() on the
  // server, so a hand-edited JSON file can't inject javascript: either.
  function safeUrl(url) {
    const value = (url || '').trim();
    if (!value) return '';
    try {
      const parsed = new URL(value, window.location.origin);
      return /^(https?|mailto):$/.test(parsed.protocol) ? parsed.href : '';
    } catch (e) {
      return '';
    }
  }

  function mediaUrl(path) {
    return '/media/' + String(path || '').replace(/^uploads\//, '');
  }

  async function apiJson(url, options) {
    const res = await fetch(url, options);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
    return data;
  }

  /* ---------------------------------------------------------------------
     Owner-only controls
     The server tells us whether this browser is signed in at /admin; the
     add/delete UI is only revealed then.
     --------------------------------------------------------------------- */
  let isAdmin = false;

  async function detectAdmin() {
    try {
      const data = await apiJson('/api/session');
      isAdmin = !!data.is_admin;
    } catch (e) {
      isAdmin = false;
    }
    document.body.classList.toggle('is-admin', isAdmin);
    ['addProjectBtn', 'addCertBtn', 'addExperienceBtn', 'addSkillBtn'].forEach((id) => {
      const btn = document.getElementById(id);
      if (btn) btn.hidden = !isAdmin;
    });
    // Signed in via session -> the manual token fields are redundant.
    ['pf-admin-token', 'cf-cert-admin-token', 'ef-admin-token', 'sf-admin-token'].forEach((id) => {
      const field = document.getElementById(id)?.closest('.field');
      if (field) field.hidden = isAdmin;
    });
  }

  function adminToken(inputId) {
    return (document.getElementById(inputId)?.value || '').trim();
  }

  function authHeaders(inputId) {
    const token = adminToken(inputId);
    return token ? { 'X-Admin-Token': token } : {};
  }

  /* ---------------------------------------------------------------------
     Manage lists (delete + edit inside the "Add" modals)
     --------------------------------------------------------------------- */
  function renderManageList(container, items) {
    if (!container) return;
    if (!items || items.length === 0) {
      container.innerHTML = '<p class="manage-empty">Nothing here yet.</p>';
      return;
    }
    container.innerHTML = items.map((it) => `
      <div class="manage-row" data-id="${escapeHtml(it.id)}">
        <span class="manage-row-title">${escapeHtml(it.title)}</span>
        <span class="manage-row-actions">
          <button type="button" class="manage-edit-btn" data-id="${escapeHtml(it.id)}" aria-label="Edit ${escapeHtml(it.title)}" title="Edit">
            <svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>
          </button>
          <button type="button" class="manage-delete-btn" data-id="${escapeHtml(it.id)}" aria-label="Delete ${escapeHtml(it.title)}" title="Delete">
            <svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M10 11v6M14 11v6"/></svg>
          </button>
        </span>
      </div>`).join('');
  }

  // Event delegation, attached once per list.
  function wireManageList({ listId, tokenInputId, endpointBase, reload, getItems, fillForm }) {
    const list = document.getElementById(listId);
    if (!list) return;

    list.addEventListener('click', async (e) => {
      const editBtn = e.target.closest('.manage-edit-btn');
      const delBtn = e.target.closest('.manage-delete-btn');
      if (!editBtn && !delBtn) return;

      const id = (editBtn || delBtn).dataset.id;

      if (editBtn) {
        const item = (getItems() || []).find((i) => i.id === id);
        if (item) fillForm(item);
        return;
      }

      if (!isAdmin && !adminToken(tokenInputId)) {
        alert('Enter your admin token above, or sign in at /admin first.');
        return;
      }
      if (!confirm('This will be permanently deleted. Continue?')) return;

      delBtn.disabled = true;
      try {
        await apiJson(`${endpointBase}/${encodeURIComponent(id)}`, {
          method: 'DELETE',
          headers: authHeaders(tokenInputId),
        });
        await reload();
      } catch (err) {
        console.warn('Delete failed', err);
        alert(err.message || 'Could not delete that.');
        delBtn.disabled = false;
      }
    });
  }

  /* ---------------------------------------------------------------------
     Tech tag icons
     --------------------------------------------------------------------- */
  const TECH_ICON_MAP = {
    python: 'devicon-python-plain colored',
    flask: 'devicon-flask-original',
    django: 'devicon-django-plain colored',
    fastapi: 'devicon-fastapi-plain colored',
    opencv: 'devicon-opencv-plain colored',
    numpy: 'devicon-numpy-original colored',
    pandas: 'devicon-pandas-original colored',
    tensorflow: 'devicon-tensorflow-original colored',
    keras: 'devicon-keras-plain colored',
    pytorch: 'devicon-pytorch-original colored',
    'scikit-learn': 'devicon-scikitlearn-plain colored',
    sklearn: 'devicon-scikitlearn-plain colored',
    html: 'devicon-html5-plain colored',
    html5: 'devicon-html5-plain colored',
    css: 'devicon-css3-plain colored',
    css3: 'devicon-css3-plain colored',
    javascript: 'devicon-javascript-plain colored',
    js: 'devicon-javascript-plain colored',
    typescript: 'devicon-typescript-plain colored',
    react: 'devicon-react-original colored',
    nodejs: 'devicon-nodejs-plain colored',
    'node.js': 'devicon-nodejs-plain colored',
    express: 'devicon-express-original',
    mongodb: 'devicon-mongodb-plain colored',
    mysql: 'devicon-mysql-plain colored',
    postgresql: 'devicon-postgresql-plain colored',
    sqlite: 'devicon-sqlite-plain colored',
    git: 'devicon-git-plain colored',
    github: 'devicon-github-original',
    docker: 'devicon-docker-plain colored',
    linux: 'devicon-linux-plain',
    aws: 'devicon-amazonwebservices-plain-wordmark colored',
    bash: 'devicon-bash-plain',
    jupyter: 'devicon-jupyter-plain colored',
    matplotlib: 'devicon-matplotlib-plain colored',
    bootstrap: 'devicon-bootstrap-plain colored',
    vuejs: 'devicon-vuejs-plain colored',
    'vue.js': 'devicon-vuejs-plain colored',
    redis: 'devicon-redis-plain colored',
    c: 'devicon-c-plain colored',
    'c++': 'devicon-cplusplus-plain colored',
    java: 'devicon-java-plain colored',
    r: 'devicon-r-plain colored',
  };

  function techIcon(tagName) {
    const cls = TECH_ICON_MAP[(tagName || '').trim().toLowerCase()];
    return cls ? `<i class="${cls} tech-tag-icon" aria-hidden="true"></i>` : '';
  }

  /* ---------------------------------------------------------------------
     Projects
     --------------------------------------------------------------------- */
  const projectGrid = document.getElementById('projectGrid');
  let projectCache = [];

  function renderProjects(projects) {
    if (!projectGrid) return;
    projectCache = projects || [];

    const countEl = document.getElementById('projectCount');
    if (countEl) countEl.textContent = projectCache.length;
    renderManageList(document.getElementById('projectManageList'), projectCache);

    if (projectCache.length === 0) {
      projectGrid.innerHTML = '<p class="projects-empty">No projects yet.</p>';
      return;
    }

    projectGrid.innerHTML = projectCache.map((p) => {
      // width/height reserve space so cards don't shift as images load.
      const thumb = p.image
        ? `<img src="${escapeHtml(mediaUrl(p.image))}" alt="${escapeHtml(p.title)}" width="640" height="360" loading="lazy" decoding="async">`
        : '<span class="work-thumb-glyph" aria-hidden="true">&lt;/&gt;</span>';
      const description = p.description ? `<p class="work-desc">${escapeHtml(p.description)}</p>` : '';
      const tags = (p.tags || []).map((t) => `<span class="tech-tag">${techIcon(t)}${escapeHtml(t)}</span>`).join('');

      const links = [];
      const code = safeUrl(p.code_url);
      const demo = safeUrl(p.demo_url);
      if (code) links.push(`<a href="${escapeHtml(code)}" target="_blank" rel="noopener noreferrer" class="work-btn-code"><svg aria-hidden="true" viewBox="0 0 24 24" fill="currentColor"><path d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.57.1.78-.25.78-.55 0-.27-.01-1.16-.02-2.11-3.2.7-3.88-1.36-3.88-1.36-.52-1.34-1.28-1.69-1.28-1.69-1.05-.72.08-.71.08-.71 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.56-.29-5.25-1.28-5.25-5.7 0-1.26.45-2.29 1.19-3.1-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.18 1.18a11 11 0 0 1 5.79 0c2.2-1.49 3.17-1.18 3.17-1.18.64 1.59.24 2.76.12 3.05.74.81 1.19 1.84 1.19 3.1 0 4.43-2.7 5.41-5.27 5.69.41.36.78 1.08.78 2.17 0 1.57-.01 2.83-.01 3.22 0 .3.2.66.79.55A10.51 10.51 0 0 0 23.5 12C23.5 5.65 18.35.5 12 .5Z"/></svg>Code</a>`);
      if (demo) links.push(`<a href="${escapeHtml(demo)}" target="_blank" rel="noopener noreferrer" class="work-btn-demo"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><path d="M15 3h6v6"/><path d="M10 14 21 3"/></svg>${escapeHtml(p.demo_text || 'Live demo')}</a>`);

      return `
        <article class="work-card">
          <div class="work-thumb">${thumb}</div>
          <div class="work-body">
            <h3>${escapeHtml(p.title)}</h3>
            ${description}
            ${tags ? `<div class="stack">${tags}</div>` : ''}
            ${links.length ? `<div class="work-links">${links.join('')}</div>` : ''}
          </div>
        </article>`;
    }).join('');
  }

  async function loadProjects() {
    if (!projectGrid) return;
    try {
      renderProjects(await apiJson('/api/projects'));
    } catch (err) {
      console.warn('Could not load projects', err);
      projectGrid.innerHTML = '<p class="projects-empty">Could not load projects right now.</p>';
    }
  }

  /* ---------------------------------------------------------------------
     Certifications
     --------------------------------------------------------------------- */
  const certGrid = document.getElementById('certGrid');
  let certCache = [];

  function certCardHtml(c) {
    const href = c.image ? mediaUrl(c.image) : safeUrl(c.link);
    const thumb = c.image
      ? `<img src="${escapeHtml(mediaUrl(c.image))}" alt="${escapeHtml(c.title)}" width="480" height="340" loading="lazy" decoding="async">`
      : '<span class="work-thumb-glyph" aria-hidden="true">&lt;/&gt;</span>';
    const tag = href ? 'a' : 'div';
    const attrs = href ? ` href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer"` : '';
    return `
      <${tag} class="cert-card"${attrs}>
        <span class="cert-thumb">${thumb}</span>
        <span class="cert-body">
          <span class="cert-title">${escapeHtml(c.title)}</span>
          ${c.issuer ? `<span class="cert-issuer">${escapeHtml(c.issuer)}</span>` : ''}
          ${c.meta ? `<span class="cert-meta">${escapeHtml(c.meta)}</span>` : ''}
        </span>
      </${tag}>`;
  }

  function renderCertifications(certifications) {
    if (!certGrid) return;
    certCache = certifications || [];
    renderManageList(document.getElementById('certManageList'), certCache);

    const countEl = document.getElementById('certCount');
    if (countEl) countEl.textContent = certCache.length;

    certGrid.innerHTML = certCache.length
      ? certCache.map(certCardHtml).join('')
      : '<p class="projects-empty">No certifications yet.</p>';
  }

  async function loadCertifications() {
    if (!certGrid) return;
    try {
      renderCertifications(await apiJson('/api/certifications'));
    } catch (err) {
      console.warn('Could not load certifications', err);
      certGrid.innerHTML = '<p class="projects-empty">Could not load certifications right now.</p>';
    }
  }

  /* ---------------------------------------------------------------------
     Experience
     --------------------------------------------------------------------- */
  const experienceTimeline = document.getElementById('experienceTimeline');
  let experienceCache = [];

  function renderExperience(experiences) {
    if (!experienceTimeline) return;
    // The manage-list widget displays `title`; alias it from `role` here
    // without losing the fields the edit form and API need.
    experienceCache = (experiences || []).map((e) => ({ ...e, title: e.role }));
    renderManageList(document.getElementById('experienceManageList'), experienceCache);

    if (experienceCache.length === 0) {
      experienceTimeline.innerHTML = '<p class="projects-empty">No experience yet.</p>';
      return;
    }

    experienceTimeline.innerHTML = experienceCache.map((e) => `
      <div class="timeline-item">
        <span class="timeline-dot" aria-hidden="true"></span>
        <div class="timeline-content">
          <h4>${escapeHtml(e.role)}${e.company ? ` <span>@ ${escapeHtml(e.company)}</span>` : ''}</h4>
          ${e.duration ? `<p class="timeline-duration">${escapeHtml(e.duration)}</p>` : ''}
          ${e.description ? `<p>${escapeHtml(e.description)}</p>` : ''}
        </div>
      </div>`).join('');
  }

  async function loadExperiences() {
    if (!experienceTimeline) return;
    try {
      renderExperience(await apiJson('/api/experiences'));
    } catch (err) {
      console.warn('Could not load experience', err);
      experienceTimeline.innerHTML = '<p class="projects-empty">Could not load experience right now.</p>';
    }
  }

  /* ---------------------------------------------------------------------
     Skills
     Categories used to be hand-written HTML; they now come from
     /api/skills so they can be added, edited, reordered and deleted from
     the same admin UI as projects/certifications/experience.
     --------------------------------------------------------------------- */
  const skillsGrid = document.getElementById('skillsGrid');
  let skillCache = [];

  // Per-category icons for the built-in cards (Programming Languages, Web
  // Development, Databases, Tools & Platforms, Cloud Platforms, AI/ML),
  // keyed by the stable id from app.py's DEFAULT_SKILLS. Any admin-added
  // custom category (no matching id) falls back to a generic chip icon -
  // a full icon picker would be needed to let admins choose per-card, which
  // is more than this form does today.
  const SKILL_ICON_SVGS = {
    'skill-languages': '<svg aria-hidden="true" focusable="false" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>',
    'skill-web': '<svg aria-hidden="true" focusable="false" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15 15 0 0 1 0 20a15 15 0 0 1 0-20"/></svg>',
    'skill-databases': '<svg aria-hidden="true" focusable="false" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/></svg>',
    'skill-tools': '<svg aria-hidden="true" focusable="false" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a4 4 0 1 0-5.4 5.4L2 19l3 3 7.3-7.3a4 4 0 0 0 5.4-5.4l-2.8 2.8-2-2Z"/></svg>',
    'skill-cloud': '<svg aria-hidden="true" focusable="false" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.5 19a4.5 4.5 0 0 0 0-9 6 6 0 0 0-11.4-1.5A5 5 0 0 0 6.5 19h11Z"/></svg>',
    'skill-ai': '<svg aria-hidden="true" focusable="false" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2"/></svg>',
  };
  const SKILL_ICON_FALLBACK = SKILL_ICON_SVGS['skill-ai'];
  function skillIconSvg(skill) {
    return SKILL_ICON_SVGS[skill.id] || SKILL_ICON_FALLBACK;
  }

  function skillTagsHtml(tags) {
    return (tags || []).map((t) => `<span>${techIcon(t)}${escapeHtml(t)}</span>`).join('');
  }

  function skillCardHtml(s, accentIndex) {
    const wide = !!s.wide;
    const accentClass = `accent-${(accentIndex % 5) + 1}`;
    // Compact cards with a lot of flat tags (e.g. "Tools & Platforms" with
    // 5 items) wrap onto a second line at the standard column width. Giving
    // them extra grid width lets the tags sit on a single row instead.
    // "Cloud Platforms" only has 3 tags but two are long labels ("Microsoft
    // Azure", "Google Cloud Platform") that don't fit at standard width
    // either, so it's called out by id alongside the generic tag-count rule
    // (which still covers any future admin-added category with many tags).
    const roomy = !wide && ((s.tags || []).length >= 5 || s.id === 'skill-cloud');
    const head = `
      <div class="skill-cat-head">
        <span class="skill-cat-icon">${skillIconSvg(s)}</span>
        <div><h4>${escapeHtml(s.title)}</h4>${s.subtitle ? `<span>${escapeHtml(s.subtitle)}</span>` : ''}</div>
      </div>`;

    let body;
    if (s.subgroups && s.subgroups.length) {
      body = `<div class="skill-subgroups">${s.subgroups.map((g) => `
        <div class="skill-subgroup">
          ${g.label ? `<p class="skill-subgroup-label">${escapeHtml(g.label)}</p>` : ''}
          <div class="skill-cat-tags">${skillTagsHtml(g.tags)}</div>
        </div>`).join('')}</div>`;
    } else {
      body = `<div class="skill-cat-tags">${skillTagsHtml(s.tags)}</div>`;
    }

    return `<div class="skill-cat-card ${accentClass}${wide ? ' skill-cat-card--wide' : ''}${roomy ? ' skill-cat-card--roomy' : ''}">${head}${body}</div>`;
  }

  function renderSkills(skills) {
    if (!skillsGrid) return;
    skillCache = skills || [];
    renderManageList(document.getElementById('skillManageList'), skillCache);

    if (skillCache.length === 0) {
      skillsGrid.innerHTML = '<p class="projects-empty">No skill categories yet.</p>';
      return;
    }

    const compact = skillCache.filter((s) => !s.wide);
    const wide = skillCache.filter((s) => s.wide);
    let html = '';
    if (compact.length) {
      html += `<div class="skills-top-grid skills-top-grid--auto">${compact.map((s, i) => skillCardHtml(s, i)).join('')}</div>`;
    }
    html += wide.map((s, i) => skillCardHtml(s, i)).join('');
    skillsGrid.innerHTML = html;
  }

  async function loadSkills() {
    if (!skillsGrid) return;
    try {
      renderSkills(await apiJson('/api/skills'));
    } catch (err) {
      console.warn('Could not load skills', err);
      skillsGrid.innerHTML = '<p class="projects-empty">Could not load skills right now.</p>';
    }
  }

  /* ---------------------------------------------------------------------
     Modals - focus trap, Esc to close, focus restored on close
     --------------------------------------------------------------------- */
  const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';
  let lastFocused = null;

  function openModal(overlay) {
    if (!overlay) return;
    lastFocused = document.activeElement;
    overlay.hidden = false;
    document.body.classList.add('modal-open');
    $(FOCUSABLE, overlay)?.focus();
  }

  function closeModal(overlay) {
    if (!overlay || overlay.hidden) return;
    overlay.hidden = true;
    document.body.classList.remove('modal-open');
    lastFocused?.focus?.();
  }

  document.addEventListener('keydown', (e) => {
    const overlay = $('.project-form-overlay:not([hidden])');
    if (!overlay) return;
    if (e.key === 'Escape') { closeModal(overlay); return; }
    if (e.key !== 'Tab') return;
    const items = $$(FOCUSABLE, overlay).filter((el) => el.offsetParent !== null);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });

  /* ---------------------------------------------------------------------
     Add / edit modal wiring, shared by projects and certifications
     --------------------------------------------------------------------- */
  function wireEntityModal(opts) {
    const overlay = document.getElementById(opts.overlayId);
    const formEl = document.getElementById(opts.formId);
    const statusEl = document.getElementById(opts.statusId);
    const titleEl = overlay ? $('.project-form-head h3', overlay) : null;
    if (!overlay || !formEl) return null;

    let editingId = null;
    const defaultTitle = titleEl ? titleEl.textContent : '';

    function resetToAdd() {
      editingId = null;
      formEl.reset();
      if (titleEl) titleEl.textContent = defaultTitle;
      if (statusEl) statusEl.textContent = '';
    }

    document.getElementById(opts.btnId)?.addEventListener('click', () => {
      resetToAdd();
      openModal(overlay);
    });
    document.getElementById(opts.closeId)?.addEventListener('click', () => closeModal(overlay));
    overlay.addEventListener('click', (e) => { if (e.target === overlay) closeModal(overlay); });

    formEl.addEventListener('submit', async (e) => {
      e.preventDefault();
      const formData = new FormData(formEl);
      // The token travels as a header, not as a form field.
      formData.delete('admin_token');

      const submitBtn = $('button[type="submit"]', formEl);
      if (submitBtn) submitBtn.disabled = true;
      if (statusEl) {
        statusEl.textContent = editingId ? 'Saving...' : 'Adding...';
        statusEl.className = 'form-status';
      }

      const url = editingId ? `${opts.endpoint}/${encodeURIComponent(editingId)}` : opts.endpoint;
      try {
        await apiJson(url, {
          method: editingId ? 'PATCH' : 'POST',
          body: formData,
          headers: authHeaders(opts.tokenInputId),
        });
        if (statusEl) {
          statusEl.textContent = editingId ? 'Saved!' : 'Added!';
          statusEl.className = 'form-status form-status--ok';
        }
        await opts.reload();
        setTimeout(() => { closeModal(overlay); resetToAdd(); }, 900);
      } catch (err) {
        console.warn(`${opts.endpoint} failed`, err);
        if (statusEl) {
          statusEl.textContent = err.message || 'Something went wrong.';
          statusEl.className = 'form-status form-status--error';
        }
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });

    return {
      startEdit(item) {
        resetToAdd();
        editingId = item.id;
        if (titleEl) titleEl.textContent = opts.editTitle;
        opts.populate(formEl, item);
        openModal(overlay);
        if (statusEl) statusEl.textContent = 'Editing an existing entry. Leave the image empty to keep the current one.';
      },
    };
  }

  const projectModal = wireEntityModal({
    btnId: 'addProjectBtn',
    overlayId: 'projectFormOverlay',
    closeId: 'closeProjectForm',
    formId: 'projectForm',
    statusId: 'projectFormStatus',
    tokenInputId: 'pf-admin-token',
    endpoint: '/api/projects',
    editTitle: 'Edit project',
    reload: loadProjects,
    populate(form, item) {
      const set = (name, value) => { const f = form.elements[name]; if (f) f.value = value || ''; };
      set('title', item.title);
      set('description', item.description);
      set('tags', (item.tags || []).join(', '));
      set('code_url', item.code_url);
      set('demo_url', item.demo_url);
      set('demo_text', item.demo_text);
    },
  });

  const certModal = wireEntityModal({
    btnId: 'addCertBtn',
    overlayId: 'certFormOverlay',
    closeId: 'closeCertForm',
    formId: 'certForm',
    statusId: 'certFormStatus',
    tokenInputId: 'cf-cert-admin-token',
    endpoint: '/api/certifications',
    editTitle: 'Edit certification',
    reload: loadCertifications,
    populate(form, item) {
      const set = (name, value) => { const f = form.elements[name]; if (f) f.value = value || ''; };
      set('title', item.title);
      set('issuer', item.issuer);
      set('meta', item.meta);
      set('link', item.link);
    },
  });

  const experienceModal = wireEntityModal({
    btnId: 'addExperienceBtn',
    overlayId: 'experienceFormOverlay',
    closeId: 'closeExperienceForm',
    formId: 'experienceForm',
    statusId: 'experienceFormStatus',
    tokenInputId: 'ef-admin-token',
    endpoint: '/api/experiences',
    editTitle: 'Edit experience',
    reload: loadExperiences,
    populate(form, item) {
      const set = (name, value) => { const f = form.elements[name]; if (f) f.value = value || ''; };
      set('role', item.role);
      set('company', item.company);
      set('duration', item.duration);
      set('description', item.description);
    },
  });

  const skillModal = wireEntityModal({
    btnId: 'addSkillBtn',
    overlayId: 'skillFormOverlay',
    closeId: 'closeSkillForm',
    formId: 'skillForm',
    statusId: 'skillFormStatus',
    tokenInputId: 'sf-admin-token',
    endpoint: '/api/skills',
    editTitle: 'Edit skill category',
    reload: loadSkills,
    populate(form, item) {
      const set = (name, value) => { const f = form.elements[name]; if (f) f.value = value || ''; };
      set('title', item.title);
      set('subtitle', item.subtitle);
      set('tags', (item.tags || []).join(', '));
      set('subgroups', (item.subgroups || [])
        .map((g) => `${g.label ? g.label + ': ' : ''}${(g.tags || []).join(', ')}`)
        .join('\n'));
      const wideEl = form.elements['wide'];
      if (wideEl) wideEl.checked = !!item.wide;
    },
  });

  /* ---------------------------------------------------------------------
     Resume upload card - opens as a modal from the hero button instead
     of navigating anywhere. Not a full CRUD entity (no edit, just
     upload/replace/remove), so it gets its own small wiring rather than
     going through wireEntityModal.
     --------------------------------------------------------------------- */
  (function wireResumeModal() {
    const overlay = document.getElementById('resumeFormOverlay');
    const form = document.getElementById('resumeForm');
    if (!overlay || !form) return;

    const statusEl = document.getElementById('resumeFormStatus');
    const noteEl = document.getElementById('resumeStatusNote');
    const delBtn = document.getElementById('deleteResumeBtn');

    document.getElementById('uploadResumeBtn')?.addEventListener('click', () => openModal(overlay));
    document.getElementById('closeResumeForm')?.addEventListener('click', () => closeModal(overlay));
    overlay.addEventListener('click', (e) => { if (e.target === overlay) closeModal(overlay); });

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const submitBtn = $('button[type="submit"]', form);
      if (submitBtn) submitBtn.disabled = true;
      if (statusEl) { statusEl.textContent = 'Uploading…'; statusEl.className = 'form-status'; }
      try {
        await apiJson('/api/resume', { method: 'POST', body: new FormData(form) });
        if (statusEl) { statusEl.textContent = 'Uploaded!'; statusEl.className = 'form-status form-status--ok'; }
        if (noteEl) noteEl.innerHTML = 'A resume is live at <code>/resume</code> right now.';
        // Reload so the hero/download-vs-remove state (server-rendered) stays in sync.
        setTimeout(() => window.location.reload(), 700);
      } catch (err) {
        if (statusEl) { statusEl.textContent = err.message || 'Could not upload that file.'; statusEl.className = 'form-status form-status--error'; }
        if (submitBtn) submitBtn.disabled = false;
      }
    });

    delBtn?.addEventListener('click', async () => {
      if (!confirm('Remove the current resume?')) return;
      delBtn.disabled = true;
      try {
        await apiJson('/api/resume', { method: 'DELETE' });
        window.location.reload();
      } catch (err) {
        alert(err.message || 'Could not remove the resume.');
        delBtn.disabled = false;
      }
    });
  })();

  wireManageList({
    listId: 'projectManageList',
    tokenInputId: 'pf-admin-token',
    endpointBase: '/api/projects',
    reload: loadProjects,
    getItems: () => projectCache,
    fillForm: (item) => projectModal?.startEdit(item),
  });

  wireManageList({
    listId: 'experienceManageList',
    tokenInputId: 'ef-admin-token',
    endpointBase: '/api/experiences',
    reload: loadExperiences,
    getItems: () => experienceCache,
    fillForm: (item) => experienceModal?.startEdit(item),
  });

  wireManageList({
    listId: 'certManageList',
    tokenInputId: 'cf-cert-admin-token',
    endpointBase: '/api/certifications',
    reload: loadCertifications,
    getItems: () => certCache,
    fillForm: (item) => certModal?.startEdit(item),
  });

  wireManageList({
    listId: 'skillManageList',
    tokenInputId: 'sf-admin-token',
    endpointBase: '/api/skills',
    reload: loadSkills,
    getItems: () => skillCache,
    fillForm: (item) => skillModal?.startEdit(item),
  });

  /* ---------------------------------------------------------------------
     Contact form
     The old version showed a cheerful "Thanks, your message has been sent"
     for ANY failure, including 400s and 500s - the user believed the
     message went through when it hadn't. Now a real HTTP error surfaces as
     an error, and only a genuine network failure falls back to the
     mailto: escape hatch.
     --------------------------------------------------------------------- */
  const contactForm = document.getElementById('contactForm');
  const contactStatus = document.getElementById('formStatus');

  contactForm?.addEventListener('submit', async (e) => {
    e.preventDefault();

    // Belt-and-suspenders: don't let a submit through until name, phone,
    // email and message are actually filled. reportValidity() re-checks the
    // required/type constraints on the fields and, if anything's missing,
    // shows the browser's native prompt pointing at the first empty one
    // instead of sending the request.
    if (!contactForm.reportValidity()) {
      return;
    }

    const payload = Object.fromEntries(new FormData(contactForm).entries());
    const submitBtn = $('button[type="submit"]', contactForm);

    if (submitBtn) submitBtn.disabled = true;
    contactStatus.textContent = 'Sending...';
    contactStatus.className = 'form-status';

    let res;
    try {
      res = await fetch('/api/contact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } catch (networkErr) {
      // fetch() only rejects when the request never reached the server.
      console.warn('Contact API unreachable', networkErr);
      contactStatus.innerHTML =
        'Could not reach the server. Please email me directly at ' +
        '<a href="mailto:dhananjaysingh90314@gmail.com">dhananjaysingh90314@gmail.com</a>.';
      contactStatus.className = 'form-status form-status--error';
      if (submitBtn) submitBtn.disabled = false;
      return;
    }

    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      contactStatus.textContent = data.error || `Could not send your message (${res.status}). Please try again.`;
      contactStatus.className = 'form-status form-status--error';
      if (submitBtn) submitBtn.disabled = false;
      return;
    }

    contactStatus.textContent = data.message || `Thanks, ${payload.name}! Your message has been sent.`;
    contactStatus.className = 'form-status form-status--ok';
    contactForm.reset();
    if (submitBtn) submitBtn.disabled = false;
  });

  /* ---------------------------------------------------------------------
     Boot
     --------------------------------------------------------------------- */
  detectAdmin();
  loadProjects();
  loadCertifications();
  loadExperiences();
  loadSkills();
})();

/* ============================================================
   VEGAS DECODED — Front-end rendering
   Reads data/videos.json (auto-generated) and data/posts.json
   and renders cards. No framework, no build step.
   ============================================================ */

(function () {
  const cfg = window.VD_CONFIG || {};

  /* ---- Mobile nav toggle ---- */
  const toggle = document.querySelector('.nav-toggle');
  const links = document.querySelector('.nav-links');
  if (toggle && links) {
    toggle.addEventListener('click', () => links.classList.toggle('open'));
  }

  /* ---- Wire up channel/social links ---- */
  document.querySelectorAll('[data-channel-link]').forEach(a => {
    if (cfg.channelUrl) a.href = cfg.channelUrl;
  });

  /* ---- Helpers ---- */
  const esc = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

  function timeAgo(iso) {
    if (!iso) return '';
    const then = new Date(iso).getTime();
    if (isNaN(then)) return '';
    const s = Math.floor((Date.now() - then) / 1000);
    const units = [['year', 31536000], ['month', 2592000], ['week', 604800],
                   ['day', 86400], ['hour', 3600], ['minute', 60]];
    for (const [name, secs] of units) {
      const v = Math.floor(s / secs);
      if (v >= 1) return `${v} ${name}${v > 1 ? 's' : ''} ago`;
    }
    return 'just now';
  }

  const playIcon = `<svg viewBox="0 0 68 48" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <path d="M66.5 7.7a8 8 0 0 0-5.6-5.7C56 .6 34 .6 34 .6s-22 0-26.9 1.4A8 8 0 0 0 1.5 7.7 84 84 0 0 0 0 24a84 84 0 0 0 1.5 16.3 8 8 0 0 0 5.6 5.7C12 47.4 34 47.4 34 47.4s22 0 26.9-1.4a8 8 0 0 0 5.6-5.7A84 84 0 0 0 68 24a84 84 0 0 0-1.5-16.3z" fill="#FF3B5C"/>
    <path d="M27 34.5 45 24 27 13.5z" fill="#fff"/></svg>`;

  function cleanTitle(t) {
    // Strip a trailing run of hashtags (e.g. "… #Shorts #LasVegas #Caesars")
    // and any leftover separator, so card titles read cleanly.
    return String(t || '')
      .replace(/(?:\s+#[\p{L}\p{N}_]+)+\s*$/u, '')
      .replace(/\s*[|·—-]\s*$/, '')
      .trim();
  }

  function isShort(v) {
    return /#shorts?\b/i.test(v.title || '');
  }

  function videoCard(v) {
    const url = `https://www.youtube.com/watch?v=${encodeURIComponent(v.id)}`;
    const thumb = v.thumbnail || `https://i.ytimg.com/vi/${encodeURIComponent(v.id)}/hqdefault.jpg`;
    const title = cleanTitle(v.title) || v.title;
    const label = isShort(v) ? 'Short' : 'Episode';
    return `<a class="card reveal" href="${url}" target="_blank" rel="noopener" aria-label="${esc(title)}">
      <div class="card-thumb">
        <img loading="lazy" src="${esc(thumb)}" alt="${esc(title)}">
        <div class="play">${playIcon}</div>
      </div>
      <div class="card-body">
        <div class="card-meta">${label}</div>
        <div class="card-title">${esc(title)}</div>
        <div class="card-foot"><span>${esc(timeAgo(v.published))}</span></div>
      </div>
    </a>`;
  }

  function postCard(p) {
    return `<a class="card post-card reveal" href="posts/${esc(p.slug)}.html" aria-label="${esc(p.title)}">
      ${p.cover ? `<div class="card-thumb"><img loading="lazy" src="${esc(p.cover)}" alt="${esc(p.title)}"></div>` : ''}
      <div class="card-body">
        <div class="post-tags">${(p.tags || []).slice(0, 3).map(t => `<span class="tag">${esc(t)}</span>`).join('')}</div>
        <div class="card-title">${esc(p.title)}</div>
        <div class="card-desc">${esc(p.excerpt)}</div>
        <div class="card-foot">
          <span>${esc(formatDate(p.date))}</span>
          <span class="read-time">${esc(p.readTime || '3 min read')}</span>
        </div>
      </div>
    </a>`;
  }

  function formatDate(iso) {
    if (!iso) return '';
    // Parse plain YYYY-MM-DD as a local date to avoid UTC timezone shifting
    // the displayed day (e.g. showing Aug 7 for an Aug 8 post).
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso).trim());
    const d = m ? new Date(+m[1], +m[2] - 1, +m[3]) : new Date(iso);
    if (isNaN(d)) return iso;
    return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
  }

  async function loadJSON(path) {
    try {
      const res = await fetch(path, { cache: 'no-cache' });
      if (!res.ok) throw new Error(res.status);
      return await res.json();
    } catch (e) {
      return null;
    }
  }

  /* ---- Render videos ---- */
  async function renderVideos() {
    const grid = document.querySelector('[data-videos]');
    if (!grid) return;
    const limit = parseInt(grid.getAttribute('data-limit') || '0', 10);
    const data = await loadJSON('data/videos.json');
    if (!data || !Array.isArray(data.videos) || data.videos.length === 0) {
      grid.innerHTML = `<div class="state">Videos will appear here automatically once the sync runs. New uploads are pulled from the channel every few hours.</div>`;
      return;
    }
    let videos = data.videos;
    const type = (grid.getAttribute('data-type') || 'all').toLowerCase();
    if (type === 'long') videos = videos.filter(v => !isShort(v));
    else if (type === 'short') videos = videos.filter(isShort);
    if (videos.length === 0) {
      grid.innerHTML = `<div class="state">No videos to show here yet — new uploads sync in automatically.</div>`;
      return;
    }
    if (limit > 0) videos = videos.slice(0, limit);
    grid.innerHTML = videos.map(videoCard).join('');
  }

  /* ---- Render posts ---- */
  async function renderPosts() {
    const grid = document.querySelector('[data-posts]');
    if (!grid) return;
    const limit = parseInt(grid.getAttribute('data-limit') || '0', 10);
    const data = await loadJSON('data/posts.json');
    // posts.json path differs for pages inside /posts/ — try fallback
    let posts = data && Array.isArray(data.posts) ? data.posts : null;
    if (!posts) {
      grid.innerHTML = `<div class="state">Posts are on the way. Each new episode becomes a 2–4 minute read here.</div>`;
      return;
    }
    posts.sort((a, b) => new Date(b.date) - new Date(a.date));
    if (limit > 0) posts = posts.slice(0, limit);
    grid.innerHTML = posts.map(postCard).join('');
  }

  renderVideos();
  renderPosts();
})();

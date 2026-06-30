// SocialPay Service Worker v10 — Full Offline Mode + PNG Icons
const CACHE_NAME = 'socialpay-v12';
const DATA_CACHE = 'socialpay-data-v12';

const STATIC_ASSETS = [
  '/static/css/style.css',
  '/static/manifest.json',
  '/static/icons/icon-192.svg',
  '/static/icons/icon-512.svg',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/apple-touch-icon.png',
  '/offline',
];
// app.js is intentionally excluded from precache — fetched fresh each time

const CACHEABLE_PAGES = [
  '/dashboard','/tasks','/balance',
  '/notifications','/my_submissions','/referrals',
  '/achievements','/leaderboard',
];
// Profile is intentionally excluded — it contains session-sensitive bank/pin data

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(STATIC_ASSETS).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => k !== CACHE_NAME && k !== DATA_CACHE).map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const req = event.request;
  const url = new URL(req.url);

  if (req.method !== 'GET') return;
  if (url.pathname.startsWith('/admin') || url.pathname.startsWith('/api/') || url.origin !== self.location.origin) return;

  if (url.pathname.startsWith('/static/')) {
    // Use networkFirst for JS files so script updates apply immediately
    if (url.pathname.endsWith('.js')) {
      event.respondWith(networkFirst(req)); return;
    }
    event.respondWith(cacheFirst(req)); return;
  }

  if (CACHEABLE_PAGES.some(p => url.pathname === p || url.pathname.startsWith(p + '?')) || url.pathname === '/') {
    event.respondWith(networkFirstPage(req)); return;
  }

  event.respondWith(networkFirst(req));
});

async function cacheFirst(req) {
  const cached = await caches.match(req);
  if (cached) return cached;
  try {
    const res = await fetch(req);
    if (res && res.status === 200) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(req, res.clone());
    }
    return res;
  } catch { return new Response('Asset unavailable offline.', { status: 503 }); }
}

async function networkFirstPage(req) {
  const cache = await caches.open(DATA_CACHE);
  try {
    const res = await fetch(req);
    if (res && res.status === 200) cache.put(req, res.clone());
    return res;
  } catch {
    const cached = await cache.match(req);
    if (cached) {
      const html = await cached.text();
      const banner = `<div id="offline-banner" style="position:fixed;top:0;left:0;right:0;z-index:99999;background:linear-gradient(135deg,#EF233C,#c0392b);color:white;padding:10px 16px;display:flex;align-items:center;justify-content:space-between;font-size:13px;font-weight:700;box-shadow:0 2px 12px rgba(0,0,0,0.3)"><span>📵 Ana nuna bayanai na ƙarshe — Babu haɗin intanet</span><button onclick="location.reload()" style="background:white;color:#EF233C;border:none;padding:5px 12px;border-radius:8px;font-weight:800;cursor:pointer;font-size:12px">🔄 Sake gwadawa</button></div><div style="height:44px"></div>`;
      const patched = html.replace(/<body([^>]*)>/, `<body$1>${banner}`);
      return new Response(patched, { status: 200, headers: { 'Content-Type': 'text/html; charset=utf-8' } });
    }
    const offlinePage = await caches.match('/offline');
    return offlinePage || new Response(OFFLINE_HTML, { status: 200, headers: { 'Content-Type': 'text/html; charset=utf-8' } });
  }
}

async function networkFirst(req) {
  try { return await fetch(req); }
  catch { const c = await caches.match(req); return c || new Response('Offline', { status: 503 }); }
}

self.addEventListener('sync', event => {
  if (event.tag === 'sync-pending-actions') {
    event.waitUntil(
      self.clients.matchAll({ type: 'window' }).then(clients =>
        clients.forEach(c => c.postMessage({ type: 'ONLINE_RESTORED' }))
      )
    );
  }
});

self.addEventListener('push', event => {
  let title = 'SocialPay';
  let body = '';
  let url = '/notifications';
  
  if (event.data) {
    try {
      const data = event.data.json();
      title = data.title || title;
      body = data.body || body;
      url = data.url || url;
    } catch {
      body = event.data.text();
    }
  }

  const options = {
    body: body,
    icon: '/static/icons/icon-192.svg',
    badge: '/static/icons/icon-192.svg',
    vibrate: [200, 100, 200, 100, 200],
    data: { url: url },
    requireInteraction: false,
    tag: 'socialpay-notif',
    renotify: true,
    actions: [
      { action: 'view', title: '👀 View' },
      { action: 'dismiss', title: '✕ Dismiss' }
    ]
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  
  // If user clicked dismiss action, just close
  if (event.action === 'dismiss') return;
  
  const url = event.notification.data?.url || '/notifications';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clients => {
      // Focus existing window if open
      const existing = clients.find(c => c.url.includes(self.location.origin));
      if (existing) {
        existing.focus();
        return existing.navigate(url);
      }
      // Otherwise open new window
      return self.clients.openWindow(url);
    })
  );
});

const OFFLINE_HTML = `<!DOCTYPE html><html lang="ha"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#0A2463"><title>SocialPay — Offline</title><style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:linear-gradient(135deg,#0A2463,#1a3a8f);min-height:100vh;display:flex;align-items:center;justify-content:center;color:white}.card{background:rgba(255,255,255,0.1);backdrop-filter:blur(10px);border-radius:24px;padding:40px 32px;text-align:center;max-width:340px;width:90%;border:1px solid rgba(255,255,255,0.2)}.icon{font-size:64px;margin-bottom:20px;display:block}h1{font-size:22px;font-weight:800;margin-bottom:10px}p{opacity:0.8;font-size:14px;line-height:1.6;margin-bottom:8px}.btn{display:block;margin-top:14px;background:white;color:#0A2463;padding:12px 28px;border-radius:14px;font-weight:800;font-size:14px;cursor:pointer;border:none;width:100%}.btn2{background:rgba(255,255,255,0.2);color:white}.tip{margin-top:20px;font-size:12px;opacity:0.7;line-height:2;text-align:left}</style></head><body><div class="card"><span class="icon">📵</span><h1>Babu Haɗin Intanet</h1><p>Ana iya duba bayananku na ƙarshe a offline.</p><p>Koma baya ko sake bude shafin da aka ziyarta.</p><button class="btn" onclick="history.back()">← Koma Baya</button><button class="btn btn2" style="margin-top:10px" onclick="location.reload()">🔄 Sake Gwadawa</button><div class="tip">✅ Dashboard (last seen)<br>✅ Tasks (cached)<br>✅ Balance & History<br>✅ Profile<br>✅ Notifications<br>❌ Aika Task<br>❌ Cire Kuɗi<br>❌ Spin</div></div></body></html>`;

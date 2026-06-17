/* Service worker cho The Touchline (PWA).
   Mục tiêu: chạy toàn màn hình + mở lại được khi mất mạng (xem lại tin/từ đã tải).
   - HTML: network-first (có mạng lấy bản mới, mất mạng dùng bản đã lưu).
   - Tài nguyên tĩnh cùng origin (icon, manifest): cache-first.
   - Gọi API (proxy Vercel, vocab-worker) khác origin & mọi POST: KHÔNG can thiệp -> đi thẳng ra mạng.
   Đổi CACHE khi cập nhật để dọn bản cũ. */
const CACHE = "touchline-v1";
const SHELL = ["/", "/index.html", "/manifest.json",
  "/icons/icon-180.png", "/icons/icon-192.png", "/icons/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE)
      .then((c) => Promise.allSettled(SHELL.map((u) => c.add(u))))   // allSettled: 1 file lỗi không chặn cài
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;                       // POST dịch/kéo tin/lưu vocab -> ra mạng
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;         // API/khác origin -> trình duyệt tự lo

  const isHTML = req.mode === "navigate" || (req.headers.get("accept") || "").includes("text/html");
  if (isHTML) {
    e.respondWith(
      fetch(req)
        .then((res) => { const copy = res.clone(); caches.open(CACHE).then((c) => c.put("/", copy)); return res; })
        .catch(() => caches.match(req).then((r) => r || caches.match("/")))
    );
    return;
  }
  e.respondWith(
    caches.match(req).then((r) => r || fetch(req).then((res) => {
      const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); return res;
    }))
  );
});

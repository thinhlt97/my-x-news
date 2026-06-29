# CLAUDE.md — The Touchline (web học tiếng Anh qua tin bóng đá trên X)

> File này dành cho Claude Code đọc để hiểu và tiếp tục dự án. Viết bằng tiếng Việt,
> phần hợp đồng API và mã định danh để nguyên tiếng Anh.

## 1. Dự án làm gì

Web app cá nhân giúp học tiếng Anh qua tin bóng đá trên X (Twitter). Luồng dùng:
1. Người dùng chọn các kênh X (Sky/Ornstein/Pearce...) và kéo tin 24h gần nhất về (chỉ phần text).
2. Mỗi tin hiện thành một ô; bấm dịch tin nào thì dịch tin đó (tiết kiệm API). Kết quả: từng câu tiếng Anh ở trên, dịch tiếng Việt ở dưới, kèm từ vựng có phiên âm IPA.
3. Lưu từ vựng vào danh sách riêng (đồng bộ giữa nhiều thiết bị qua "mã cá nhân").
4. Ôn tập: chọn từ → tạo 10 câu trắc nghiệm ABCD (toàn tiếng Anh, phương án gây nhiễu khó đoán).
5. Luyện nghe (kiểu IELTS): chọn từ (tay hoặc ngẫu nhiên) → tạo một đoạn hội thoại tiếng Anh tự nhiên có chứa các từ đó → đọc thành tiếng bằng TTS (Web Speech API) → trả lời 6-8 câu hỏi trộn điền từ + trắc nghiệm A/B/C. Lời thoại ẩn khi làm, nộp bài xong mới hiện kèm dịch.

Giao diện tiếng Việt, phong cách "tờ báo thể thao" (font Newsreader + Be Vietnam Pro).

## 2. Kiến trúc tổng thể

```
[Trình duyệt: index.html trên Cloudflare]
   │  (kéo tin / dịch / tạo đề)            │ (lưu/đọc từ vựng theo mã)
   ▼                                        ▼
[Proxy trên Vercel, vùng Mỹ iad1]      [vocab-worker trên Cloudflare + KV]
   ├─ twitterapi.io  (kéo tweet)
   ├─ Gemini API     (dịch / tạo đề)
   └─ Groq API       (dịch / tạo đề)
```

Có 3 codebase riêng (3 repo / thư mục):

### A. Frontend — repo `my-x-news`
- File chính: `index.html` (1 file gồm HTML + CSS + JS, không framework).
- Host: Cloudflare (Workers Builds phục vụ static asset). URL: `https://my-x-news.thinhlt1069-xnews.workers.dev`.
- Deploy: push lên GitHub `main` → Cloudflare tự build bằng `npx wrangler deploy`.
- Hằng số cấu hình ở đầu thẻ `<script>`:
  - `WORKER_URL` = URL proxy Vercel, có đuôi `/api/translate`.
  - `VOCAB_URL` = URL vocab-worker.
  - `SOURCES` = mảng handle các kênh X (sửa ở đây để thêm/bớt nguồn).
  - `VKEY`, `CODEKEY` = khóa localStorage (bản mirror + mã cá nhân).
- 5 tab: `#view-news`, `#view-vocab`, `#view-quiz`, `#view-listen` (Luyện nghe), `#view-reviewed` (Đã ôn).
- Dịch: mỗi ô tin có 2 nút (`data-p="gemini"` / `data-p="groq"`), gọi `callProxy({tweets:[text], provider})`.
- Tạo đề: nút `#makeQuiz*` → `makeQuiz(provider)`.
- Luyện nghe: nút `#makeListen*` → `makeListen(provider)` → `renderListen(data, chosen)`. Chấm điền từ bằng `normAns()` so với `answer`+`accept`. Từ vừa nghe cũng vào tab "Đã ôn" và tăng `quizCount` (như tạo đề).
  - **Phát audio (audio THẬT để tua được):** `createListenAudio(turns)` tạo audio lúc bấm Phát lần đầu (gọi proxy `body.tts`), bọc PCM→WAV bằng `pcmToWavUrl()` rồi phát qua `<audio>`. Có thanh trượt thời gian (kéo tua), nút ◀/▶ tua ±2 giây, chỉnh tốc độ (`playbackRate`). **Phím tắt** (`curAudioPlayer` + keydown toàn cục): phím cách = phát/dừng, ◀ ▶ = tua ±2s (bỏ qua khi đang gõ ô điền từ). Rời tab nghe thì `pause`.
  - **Vì sao không dùng Web Speech API làm chính:** giọng máy trình duyệt KHÔNG tua theo giây được (chỉ pause/resume). `makeSpeaker(turns)` (đọc tuần tự bằng `onend`) nay chỉ còn là **dự phòng** (nút "Đọc bằng giọng máy") khi Gemini TTS lỗi.
  - iOS/PWA: do autoplay policy, lần bấm Phát đầu có thể chỉ tạo audio — bấm lần nữa là chạy (audio đã sẵn). Audio tạo lại mỗi bài, không cache.
- `callProxy(payload, statusEl)` tự thử lại khi gặp lỗi tạm thời (429 rate limit, 503/502/500 server bận).

### B. Proxy — repo `x-translate-proxy` (trên Vercel)
- File chính: `api/translate.js` (Vercel Serverless Function). `vercel.json` ghim vùng `iad1` (Mỹ).
- **Vì sao đặt ở Vercel chứ không Cloudflare:** Gemini/Anthropic chặn theo vị trí; Cloudflare Worker hay chạy ở Hong Kong → bị chặn ("User location is not supported" / 403). Vercel iad1 ở Mỹ nên không bị chặn. ĐỪNG chuyển proxy LLM về Cloudflare Worker.
- Một endpoint `/api/translate`, phân nhánh theo hình dạng body (xem mục 3).
- Hỗ trợ 2 nhà cung cấp LLM, chọn bằng `body.provider` ("gemini" | "groq", mặc định gemini).
- Model: `gemini-2.5-flash`, `llama-3.3-70b-versatile`; **TTS** dùng `gemini-2.5-flash-preview-tts` (đa giọng, 2 giọng `Puck`/`Kore`) qua `callGeminiTTS()`.

### C. vocab-worker — Cloudflare Worker + KV
- File: `src/index.js`, `wrangler.toml` (bind KV namespace tên `VOCAB`).
- Lưu từ vựng theo "mã cá nhân" (chuỗi do người dùng tự đặt). Nhập cùng mã trên nhiều thiết bị → dùng chung danh sách.
- Deploy bằng `npx wrangler deploy` (KV không bị giới hạn vùng nên để ở Cloudflare được).

## 3. Hợp đồng API (giữa frontend và proxy `/api/translate`)

Tất cả là `POST` JSON. Phân nhánh theo trường có trong body:

**Kéo tin** (không dùng LLM, dùng twitterapi.io):
```
→ { "source": "David_Ornstein" }
← { "tweets": [ { "text": "...", "created_at": "dd-mm hh:mm" } ] }   // đã lọc 24h, bỏ RT/reply, bỏ link t.co
```

**Dịch** (gộp nhiều tweet/lần):
```
→ { "tweets": ["text1","text2"], "provider": "gemini"|"groq" }
← { "tweets": [ { "sentences": [ { "en","vi","vocab":[{ "word","ipa","pos","meaning_vi","note" }] } ] } ] }
```

**Tạo đề ôn tập:**
```
→ { "quiz": [ { "word","ipa","pos","meaning_vi" } ], "provider": "gemini"|"groq" }
← { "questions": [ { "question", "options": ["A","B","C","D"], "correct": 0..3 } ] }
```

**Luyện nghe** (tạo hội thoại + câu hỏi kiểu IELTS):
```
→ { "listen": [ { "word","ipa","pos","meaning_vi" } ], "provider": <provider> }
← { "title", "transcript": [ { "speaker","text","vi" } ],
    "questions": [
      { "type":"mc",   "q", "options":["A","B","C"], "correct":0..2, "vi","explain","evidence" },
      { "type":"fill", "q", "answer", "accept":[...], "limit", "vi","explain","evidence" }
    ] }
// SYS_LISTEN: hội thoại 2 người ~150-230 từ, lồng toàn bộ từ; 6-8 câu trộn fill+mc.
// Đáp án "fill" PHẢI là chữ có thật trong transcript để chấm tự động được.
```

**TTS luyện nghe** (đọc hội thoại thành tiếng — audio thật để tua được):
```
→ { "tts": [ { "speaker","text" } ] }     // không cần provider, luôn dùng Gemini TTS
← { "audio": "<base64 PCM 16-bit>", "mime": "audio/L16;codec=pcm;rate=24000" }
// Frontend bọc PCM->WAV (pcmToWavUrl) rồi phát. Gán 2 speaker đầu vào 2 giọng khác nhau.
// Giới hạn tổng text ~3000 ký tự để tránh quá tải/tốn quota.
```

**vocab-worker** (endpoint riêng, query `?code=MA`):
```
GET  ?code=MA              ← { "vocab": [ { "word","ipa","pos","meaning_vi" } ] }
POST ?code=MA { vocab:[] } ← { "ok": true, "count": n }
```

Lỗi luôn trả `{ "error": "..." }` kèm header CORS, để frontend hiện được lý do thật.

## 4. Biến môi trường (KHÔNG để khóa trong code/frontend)

- **Vercel (dự án x-translate-proxy):** `GEMINI_API_KEY`, `GROQ_API_KEY`, `TWITTERAPI_KEY`.
- **vocab-worker (Cloudflare):** không cần khóa; cần bind KV namespace `VOCAB` trong `wrangler.toml`.
- Đổi env trên Vercel xong **phải Redeploy** mới có hiệu lực.
- CORS: cả proxy lẫn vocab-worker có mảng `ALLOWED_ORIGINS` phải chứa URL frontend (KHÔNG kèm dấu `/` cuối).

## 5. Triển khai

- **Frontend (my-x-news):** sửa trên GitHub → push `main` → Cloudflare tự deploy. ĐỪNG chạy `npx wrangler deploy` từ thư mục local đã cũ (sẽ đè bản cũ lên — đã từng gây ra sự cố web hiện bản cũ). Nếu deploy local thì `git pull` trước.
- **Proxy (x-translate-proxy):** push GitHub → Vercel tự deploy. Đổi env thì Redeploy.
- **vocab-worker:** `npx wrangler deploy` (cần tạo KV: `npx wrangler kv namespace create VOCAB` rồi dán id vào `wrangler.toml`).

## 6. Bài học / gotcha quan trọng (đã gặp thật)

- **Chặn vùng:** LLM API (Gemini, Anthropic) chặn theo vị trí máy gọi. Cloudflare Worker chạy ở HK → 400/403. Phải gọi LLM từ Vercel (iad1, Mỹ). Đây là lý do tồn tại của proxy Vercel.
- **Rate limit:**
  - twitterapi.io trả 429 khi gọi nhiều kênh dồn dập → frontend kéo từng nguồn, nghỉ ~1.5s giữa các nguồn.
  - Gemini/Groq giới hạn theo phút (RPM/TPM). Groq tính cả `max_tokens` vào TPM → giữ `max_tokens` vừa phải (~3500-4000).
  - `callProxy` ở frontend tự chờ-thử-lại khi 429 (chờ ~14s) hoặc 503/502/500 (5/10/15s).
  - Gộp nhiều tweet/lần (batch) để giảm số request.
- **Deploy frontend:** đã từng bị web hiện bản cũ vì có bản "Manually deployed" từ local cũ đè lên bản git. Luôn ưu tiên deploy qua git.
- **Cache:** sau deploy nên `Ctrl+Shift+R` / cửa sổ ẩn danh; nếu vẫn cũ thì là lỗi deploy chứ không phải cache.
- **Lưu từ vựng:** localStorage chỉ theo từng trình duyệt; muốn đồng bộ đa thiết bị thì dùng vocab-worker + mã cá nhân.
- **Chất lượng:** Gemini dịch tiếng Việt tự nhiên hơn; Groq (Llama 3.3 70B) nhanh và miễn phí rộng hơn nhưng đôi khi kém mượt. Đề ôn tập đã yêu cầu phương án nhiễu là từ thật/cùng loại để khó đoán (chọn ≥5 từ thì đề hay hơn).
- **TTS luyện nghe:** Gemini TTS trả **PCM 16-bit thô** (mime `audio/L16;...;rate=24000`), KHÔNG phải mp3/wav — frontend phải tự bọc header WAV mới phát được. Audio cả đoạn ~25s ⇒ base64 ~1-1.5MB trong JSON (Vercel chịu được). Tạo audio tốn thêm quota Gemini TTS + vài giây độ trễ ⇒ tạo lười (chỉ khi bấm Phát). Web Speech API không tua theo giây được nên chỉ để dự phòng.

## 7. Trạng thái hiện tại

- Đang hoạt động: kéo tin theo yêu cầu, dịch (2 nút Gemini/Groq), từ vựng + IPA, lưu/đồng bộ qua mã, ôn tập trắc nghiệm, luyện nghe kiểu IELTS (hội thoại + TTS + điền từ/trắc nghiệm), tab "Đã ôn".
- Luyện nghe đọc bằng Web Speech API của trình duyệt: giọng phụ thuộc thiết bị; trên iOS/PWA phải bấm ▶ (cần thao tác người dùng), có nút "Hiện lời thoại" fallback nếu máy không hỗ trợ TTS.
- Đã TẮT việc kéo tin tự động hàng ngày (GitHub Action `daily.yml` disabled). `digest.json` và `fetch_digest.py` không còn dùng (logic kéo tin đã chuyển vào proxy `fetchSource`), nhưng vẫn còn trong repo — có thể xóa nếu muốn dọn.

## 8. Gợi ý hướng phát triển tiếp (TODO)

- Dọn file cũ không dùng: `fetch_digest.py`, `digest.json`, `daily.yml`.
- Không upload thư mục `.git`/file rác làm static asset (thêm cấu hình assets/`.assetsignore` cho Cloudflare).
- Cho phép sửa danh sách `SOURCES` ngay trên giao diện thay vì sửa code.
- Lưu lịch sử điểm ôn tập; chế độ ôn lại từ hay sai (spaced repetition).
- Phát âm thành tiếng cho từ vựng (Web Speech API).
- Cân nhắc gộp 3 thành phần về ít nơi hơn (nhưng giữ phần gọi LLM ở vùng Mỹ).

## 9. Quy ước

- Giao diện và thông báo cho người dùng: tiếng Việt.
- Không dùng framework ở frontend (thuần HTML/CSS/JS, dễ host tĩnh).
- Mọi khóa API nằm ở server (Vercel env), frontend chỉ gọi proxy.
- Design tokens (màu/font) khai báo trong `:root` của `index.html`.

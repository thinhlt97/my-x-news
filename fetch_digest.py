#!/usr/bin/env python3
"""
fetch_digest.py — Tổng hợp tin bài 24h gần nhất từ các kênh X (Twitter).

Lấy phần TEXT của tweet (bỏ qua ảnh/video) từ các kênh đã cấu hình,
xuất ra file digest.txt theo đúng định dạng để dán vào web app "The Touchline".
Tùy chọn --translate sẽ gọi Claude API dịch + giải thích từ vựng và xuất digest.md.

Cách chạy:
    export TWITTERAPI_KEY="xxx"          # khóa của twitterapi.io
    export ANTHROPIC_API_KEY="sk-ant..." # chỉ cần khi dùng --translate
    python fetch_digest.py               # chỉ lấy tin -> digest.txt
    python fetch_digest.py --translate   # lấy tin + dịch -> digest.md

Cài đặt:
    pip install requests anthropic
"""

import os
import sys
import json
import argparse
from datetime import datetime, timedelta, timezone

import requests

# ----------------------------------------------------------------------
# CẤU HÌNH
# ----------------------------------------------------------------------
ACCOUNTS = [
    "David_Ornstein",
    "JamesPearceLFC",
    "EBL2017",
    "_pauljoyce",
    "FabrizioRomano",
    "BBCSport",
]

HOURS_BACK = 24          # khoảng thời gian quan tâm
MAX_PER_ACCOUNT = 20     # giới hạn số tweet đọc mỗi kênh (kiểm soát chi phí)
INCLUDE_REPLIES = False  # bỏ qua các tweet trả lời người khác
INCLUDE_RETWEETS = False # bỏ qua retweet (chỉ lấy bài gốc của kênh)

# twitterapi.io — dịch vụ bên thứ ba, không cần tài khoản developer của X.
# Endpoint/tham số có thể thay đổi: kiểm tra https://docs.twitterapi.io
API_BASE = "https://api.twitterapi.io"
API_KEY = os.environ.get("TWITTERAPI_KEY", "")


def clean_text(text: str) -> str:
    """Bỏ link media t.co ở cuối và khoảng trắng thừa, chỉ giữ phần chữ."""
    import re
    # Bỏ các link t.co (thường là ảnh/video/quote đính kèm)
    text = re.sub(r"https://t\.co/\w+", "", text)
    # Gộp khoảng trắng/dòng trống thừa
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_account(handle: str, since: datetime) -> list[dict]:
    """
    Lấy các tweet mới nhất của một kênh, lọc theo mốc thời gian `since`.
    Trả về list dict: {"text", "created_at"}.
    """
    if not API_KEY:
        raise RuntimeError("Chưa đặt biến môi trường TWITTERAPI_KEY.")

    url = f"{API_BASE}/twitter/user/last_tweets"
    headers = {"x-api-key": API_KEY}
    params = {"userName": handle, "count": MAX_PER_ACCOUNT}

    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    payload = resp.json()

    # Cấu trúc trả về tùy phiên bản API; xử lý vài khả năng phổ biến.
    raw_tweets = (
        payload.get("tweets")
        or payload.get("data", {}).get("tweets")
        or payload.get("data")
        or []
    )

    results = []
    for tw in raw_tweets:
        text = tw.get("text") or tw.get("full_text") or ""
        created = tw.get("createdAt") or tw.get("created_at") or ""

        # Lọc retweet / reply nếu cần
        if not INCLUDE_RETWEETS and (tw.get("retweeted_tweet") or text.startswith("RT @")):
            continue
        if not INCLUDE_REPLIES and (tw.get("isReply") or tw.get("inReplyToId")):
            continue

        # Lọc theo thời gian
        ts = parse_time(created)
        if ts and ts < since:
            continue

        text = clean_text(text)
        if not text:   # tweet chỉ có ảnh/video, không có chữ -> bỏ
            continue

        results.append({
            "text": text,
            "created_at": ts.strftime("%d-%m-%Y %H:%M") if ts else "",
        })
    return results


def parse_time(s: str):
    """Thử vài định dạng thời gian thường gặp từ X."""
    if not s:
        return None
    fmts = [
        "%a %b %d %H:%M:%S %z %Y",   # Twitter cổ điển
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
    ]
    for f in fmts:
        try:
            dt = datetime.strptime(s, f)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def build_digest(grouped: dict[str, list[dict]]) -> str:
    """Tạo chuỗi digest theo định dạng web app hiểu được."""
    blocks = []
    for handle, tweets in grouped.items():
        for tw in tweets:
            header = f"@{handle} | {tw['created_at']}".strip(" |")
            blocks.append(f"{header}\n{tw['text']}")
    return "\n---\n".join(blocks)


# ----------------------------------------------------------------------
# TÙY CHỌN: dịch bằng Claude API
# ----------------------------------------------------------------------
SYSTEM_PROMPT = """Bạn là giáo viên song ngữ Anh-Việt chuyên tin bóng đá trên X.
Với đoạn tweet được cho, CHỈ trả về JSON hợp lệ (không markdown, không giải thích thừa) dạng:
{"sentences":[{"en":"<câu tiếng Anh nguyên văn>","vi":"<dịch tiếng Việt tự nhiên>",
"vocab":[{"word":"<từ/cụm đáng học>","pos":"<từ loại tiếng Việt>","meaning_vi":"<nghĩa>","note":"<ghi chú ngữ cảnh hoặc rỗng>"}]}]}
Ưu tiên thuật ngữ bóng đá, idiom, phrasal verb, từ chuyển nhượng. Mỗi câu 2-5 từ vựng.
Tách tweet thành từng câu, giữ nguyên văn tiếng Anh. Chỉ xuất JSON."""


def translate_block(client, text: str) -> dict:
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}],
    )
    raw = "".join(b.text for b in msg.content if b.type == "text")
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


def render_markdown(grouped: dict[str, list[dict]], client) -> str:
    today = datetime.now().strftime("%d-%m-%Y")
    md = [f"# Bản tin bóng đá — Học tiếng Anh ({today})\n"]
    for handle, tweets in grouped.items():
        for tw in tweets:
            md.append(f"\n## @{handle}  ·  {tw['created_at']}\n")
            try:
                parsed = translate_block(client, tw["text"])
            except Exception as e:
                md.append(f"> _Không dịch được: {e}_\n")
                continue
            for i, s in enumerate(parsed.get("sentences", []), 1):
                md.append(f"**{i}. {s['en']}**")
                md.append(f"> {s['vi']}")
                for v in s.get("vocab", []):
                    note = f" — {v['note']}" if v.get("note") else ""
                    md.append(f"- `{v['word']}` *({v.get('pos','')})*: {v['meaning_vi']}{note}")
                md.append("")
    return "\n".join(md)


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Tổng hợp tin X 24h + học tiếng Anh")
    ap.add_argument("--translate", action="store_true",
                    help="Dịch + giải nghĩa bằng Claude, xuất digest.md")
    args = ap.parse_args()

    since = datetime.now(timezone.utc) - timedelta(hours=HOURS_BACK)
    grouped = {}

    for handle in ACCOUNTS:
        try:
            tweets = fetch_account(handle, since)
            grouped[handle] = tweets
            print(f"  @{handle}: {len(tweets)} tweet trong {HOURS_BACK}h", file=sys.stderr)
        except Exception as e:
            print(f"  ! Lỗi với @{handle}: {e}", file=sys.stderr)
            grouped[handle] = []

    total = sum(len(v) for v in grouped.values())
    if total == 0:
        print("Không lấy được tweet nào. Kiểm tra TWITTERAPI_KEY và kết nối.", file=sys.stderr)
        sys.exit(1)

    # Luôn xuất digest.txt để dán thủ công vào web app
    digest = build_digest(grouped)
    with open("digest.txt", "w", encoding="utf-8") as f:
        f.write(digest)
    print(f"Đã ghi digest.txt ({total} tweet) — dán vào web app để học.", file=sys.stderr)

    # Xuất digest.json để web app deploy đọc tự động (không dịch sẵn -> tiết kiệm)
    digest_json = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "accounts": [
            {"handle": h, "tweets": tw} for h, tw in grouped.items()
        ],
    }
    with open("digest.json", "w", encoding="utf-8") as f:
        json.dump(digest_json, f, ensure_ascii=False, indent=2)
    print(f"Đã ghi digest.json — web app sẽ tự đọc file này.", file=sys.stderr)

    # Tùy chọn dịch sẵn
    if args.translate:
        try:
            from anthropic import Anthropic
        except ImportError:
            print("Cần: pip install anthropic", file=sys.stderr); sys.exit(1)
        client = Anthropic()  # đọc ANTHROPIC_API_KEY từ môi trường
        md = render_markdown(grouped, client)
        with open("digest.md", "w", encoding="utf-8") as f:
            f.write(md)
        print("Đã ghi digest.md (đã dịch + giải nghĩa).", file=sys.stderr)


if __name__ == "__main__":
    main()

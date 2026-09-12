"""
Polygon Arbitrage Scanner — KyberSwap Elastic vs QuickSwap v3
================================================================
يفحص هذا السكربت مجمعات السيولة على منصتي KyberSwap Elastic وQuickSwap v3
على شبكة Polygon (عبر GeckoTerminal Public API — لا يحتاج أي مفتاح API)،
يطبّق فلاتر السيولة/الحجم/عدد المعاملات، يطابق العملات المشتركة بين المنصتين،
يحسب فرق السعر والربح الصافي التقريبي، ثم يرسل النتائج إلى بوت تيليجرام.

يعمل جاهزاً على Railway.com كـ Worker يتكرر كل N دقيقة (انظر متغير SCAN_INTERVAL_MINUTES).

المتغيرات البيئية المطلوبة (ضعها في Railway > Variables):
    TELEGRAM_BOT_TOKEN   -> توكن البوت من BotFather
    TELEGRAM_CHAT_ID     -> الـ chat_id الذي سيستقبل الرسائل (شخصي أو قناة/مجموعة)

اختياري:
    SCAN_INTERVAL_MINUTES  (افتراضي 15)
    MIN_LIQUIDITY_USD       (افتراضي 1000)
    MAX_LIQUIDITY_USD       (افتراضي 10000)
    MIN_VOLUME_USD          (افتراضي 500)
    MAX_VOLUME_USD          (افتراضي 10000)
    MIN_TXNS_24H            (افتراضي 20)
    MAX_TXNS_24H            (افتراضي 300)
    MIN_TRADERS_24H         (افتراضي 10)
    MAX_TRADERS_24H         (افتراضي 100)
    MIN_PRICE_DIFF_PCT      (افتراضي 1.5)
    MAX_PRICE_DIFF_PCT      (افتراضي 15)
"""

import os
import time
import logging
import requests
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# الإعدادات
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("arb-scanner")

GECKOTERMINAL_BASE = "https://api.geckoterminal.com/api/v2"
NETWORK = "polygon_pos"

# أسماء الـ DEX slugs كما تظهر في GeckoTerminal لشبكة Polygon
KYBER_DEX_SLUG = "kyberswap-elastic"
QUICKSWAP_DEX_SLUG = "quickswap-v3"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

SCAN_INTERVAL_MINUTES = float(os.environ.get("SCAN_INTERVAL_MINUTES", 15))

MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 1000))
MAX_LIQUIDITY_USD = float(os.environ.get("MAX_LIQUIDITY_USD", 10000))
MIN_VOLUME_USD = float(os.environ.get("MIN_VOLUME_USD", 500))
MAX_VOLUME_USD = float(os.environ.get("MAX_VOLUME_USD", 10000))
MIN_TXNS_24H = int(os.environ.get("MIN_TXNS_24H", 20))
MAX_TXNS_24H = int(os.environ.get("MAX_TXNS_24H", 300))
MIN_TRADERS_24H = int(os.environ.get("MIN_TRADERS_24H", 10))
MAX_TRADERS_24H = int(os.environ.get("MAX_TRADERS_24H", 100))
MIN_PRICE_DIFF_PCT = float(os.environ.get("MIN_PRICE_DIFF_PCT", 1.5))
MAX_PRICE_DIFF_PCT = float(os.environ.get("MAX_PRICE_DIFF_PCT", 15))

# رموز الشبكة الأم / الأصول الكبرى المستبعدة (على Polygon)
EXCLUDED_SYMBOLS = {
    "POL", "MATIC", "WMATIC", "WETH", "ETH", "WPOL",
    "USDC", "USDC.E", "USDT", "DAI", "WBTC",
}

# تقديرات تقريبية للرسوم والغاز (Polygon غاز رخيص جداً)
KYBER_FEE_PCT_DEFAULT = 0.0008 * 100      # كنسبة مئوية تقريبية افتراضية (0.008%-0.05% حسب المجمع)
QUICKSWAP_FEE_PCT_DEFAULT = 0.003 * 100   # افتراضي متوسط لـ QuickSwap v3 (يمكن أن يكون 0.01%-1%)
ESTIMATED_GAS_USD_PER_SWAP = 0.03         # غاز تقريبي لكل عملية سواب على Polygon
NUMBER_OF_SWAPS = 2                       # شراء من منصة + بيع من الأخرى
SLIPPAGE_SAFETY_FACTOR = 0.5              # نفترض أن نصف قيمة $100 تنزلق بسبب ضعف السيولة (تحفظي)


# ---------------------------------------------------------------------------
# طبقة الاتصال بـ GeckoTerminal
# ---------------------------------------------------------------------------

def gt_get(path, params=None, retries=3):
    """طلب GET عام لـ GeckoTerminal API مع معالجة حدود المعدل (rate limit)."""
    url = f"{GECKOTERMINAL_BASE}{path}"
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=20,
                                 headers={"Accept": "application/json"})
            if resp.status_code == 429:
                wait = 15 * attempt
                log.warning(f"Rate limited (429). الانتظار {wait}s ...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            log.warning(f"خطأ في الطلب ({attempt}/{retries}): {e}")
            time.sleep(5 * attempt)
    log.error(f"فشل الطلب نهائياً: {url}")
    return None


def fetch_all_pools(dex_slug, max_pages=10):
    """
    يجلب كل المجمعات (pools) لمنصة معينة على Polygon، مع بيانات التوكنات المرتبطة.
    GeckoTerminal يُرجع 20 نتيجة لكل صفحة تقريباً.
    """
    all_pools = []
    included_lookup = {}

    for page in range(1, max_pages + 1):
        data = gt_get(
            f"/networks/{NETWORK}/dexes/{dex_slug}/pools",
            params={"page": page, "include": "base_token,quote_token"},
        )
        if not data or "data" not in data or not data["data"]:
            break

        # بناء قاموس بحث للتوكنات المرفقة (included) حسب النوع + المعرف
        for item in data.get("included", []):
            key = (item["type"], item["id"])
            included_lookup[key] = item

        all_pools.extend(data["data"])

        # احترام حد المعدل للاستخدام بدون مفتاح (~10-30 طلب/دقيقة)
        time.sleep(2.5)

        # إن كانت هذه آخر صفحة فعلياً (أقل من الحجم المعتاد) نتوقف
        if len(data["data"]) < 20:
            break

    return all_pools, included_lookup


def resolve_token(included_lookup, rel_type, rel_id):
    key = (rel_type, rel_id)
    token = included_lookup.get(key)
    if not token:
        return None
    attrs = token.get("attributes", {})
    return {
        "address": attrs.get("address"),
        "symbol": (attrs.get("symbol") or "").upper(),
        "name": attrs.get("name"),
    }


# ---------------------------------------------------------------------------
# استخراج وتصفية المجمعات المؤهلة
# ---------------------------------------------------------------------------

def extract_pool_metrics(pool, included_lookup, dex_label):
    """يحوّل بيانات مجمع خام من GeckoTerminal إلى قاموس مبسّط بالمقاييس المطلوبة."""
    attrs = pool.get("attributes", {})
    rels = pool.get("relationships", {})

    base_rel = rels.get("base_token", {}).get("data") or {}
    quote_rel = rels.get("quote_token", {}).get("data") or {}

    base_token = resolve_token(included_lookup, base_rel.get("type"), base_rel.get("id"))
    quote_token = resolve_token(included_lookup, quote_rel.get("type"), quote_rel.get("id"))

    if not base_token or not quote_token:
        return None

    try:
        liquidity_usd = float(attrs.get("reserve_in_usd") or 0)
        volume_24h = float((attrs.get("volume_usd") or {}).get("h24") or 0)
        txns_24h_obj = (attrs.get("transactions") or {}).get("h24") or {}
        buys = int(txns_24h_obj.get("buys") or 0)
        sells = int(txns_24h_obj.get("sells") or 0)
        buyers = int(txns_24h_obj.get("buyers") or 0)
        sellers = int(txns_24h_obj.get("sellers") or 0)
        base_price_usd = float(attrs.get("base_token_price_usd") or 0)
    except (TypeError, ValueError):
        return None

    total_txns = buys + sells
    # تقدير عدد المتداولين الفريدين: لا يوفر GeckoTerminal رقماً موحّداً فريداً،
    # فنأخذ الأكبر بين المشترين والبائعين كتقدير تحفظي (وليس مجموعهما لتفادي التكرار).
    approx_traders = max(buyers, sellers)

    return {
        "dex": dex_label,
        "pool_address": attrs.get("address"),
        "pool_name": attrs.get("name"),
        "base_token": base_token,
        "quote_token": quote_token,
        "price_usd": base_price_usd,
        "liquidity_usd": liquidity_usd,
        "volume_24h_usd": volume_24h,
        "txns_24h": total_txns,
        "traders_24h": approx_traders,
    }


def passes_filters(m):
    if m is None:
        return False
    if m["base_token"]["symbol"] in EXCLUDED_SYMBOLS:
        return False
    if not (MIN_LIQUIDITY_USD <= m["liquidity_usd"] <= MAX_LIQUIDITY_USD):
        return False
    if not (MIN_VOLUME_USD <= m["volume_24h_usd"] <= MAX_VOLUME_USD):
        return False
    if not (MIN_TXNS_24H <= m["txns_24h"] <= MAX_TXNS_24H):
        return False
    if not (MIN_TRADERS_24H <= m["traders_24h"] <= MAX_TRADERS_24H):
        return False
    if m["price_usd"] <= 0:
        return False
    return True


# ---------------------------------------------------------------------------
# مطابقة العملات المشتركة بين المنصتين وحساب فرص المراجحة
# ---------------------------------------------------------------------------

def build_candidate_map(pools_raw, included_lookup, dex_label):
    candidates = {}
    for pool in pools_raw:
        m = extract_pool_metrics(pool, included_lookup, dex_label)
        if not passes_filters(m):
            continue
        token_addr = m["base_token"]["address"].lower()
        # إن وُجد أكثر من مجمع لنفس التوكن على نفس المنصة، نأخذ الأعلى سيولة
        if token_addr not in candidates or m["liquidity_usd"] > candidates[token_addr]["liquidity_usd"]:
            candidates[token_addr] = m
    return candidates


def estimate_net_profit_per_100(price_diff_pct, kyber_fee_pct, quick_fee_pct):
    """
    تقدير مبسّط للربح الصافي لكل $100:
    الربح الإجمالي = 100 * (فرق السعر%)
    نطرح: رسوم المنصتين + غاز عمليتي السواب + هامش انزلاق تحفظي بسبب ضعف السيولة.
    """
    gross_profit = 100 * (price_diff_pct / 100)
    fees_cost = 100 * ((kyber_fee_pct + quick_fee_pct) / 100)
    gas_cost = ESTIMATED_GAS_USD_PER_SWAP * NUMBER_OF_SWAPS
    # انزلاق تحفظي: كلما قلت السيولة زاد الانزلاق الفعلي عن السعر المعروض
    slippage_cost = gross_profit * SLIPPAGE_SAFETY_FACTOR
    net = gross_profit - fees_cost - gas_cost - slippage_cost
    return round(net, 4)


def find_arbitrage_opportunities(kyber_candidates, quick_candidates):
    opportunities = []
    common_addresses = set(kyber_candidates) & set(quick_candidates)

    for addr in common_addresses:
        k = kyber_candidates[addr]
        q = quick_candidates[addr]

        price_k = k["price_usd"]
        price_q = q["price_usd"]
        if price_k <= 0 or price_q <= 0:
            continue

        avg_price = (price_k + price_q) / 2
        diff_pct = abs(price_k - price_q) / avg_price * 100

        if not (MIN_PRICE_DIFF_PCT <= diff_pct <= MAX_PRICE_DIFF_PCT):
            continue

        net_profit_100 = estimate_net_profit_per_100(
            diff_pct, KYBER_FEE_PCT_DEFAULT, QUICKSWAP_FEE_PCT_DEFAULT
        )

        opportunities.append({
            "symbol": k["base_token"]["symbol"] or q["base_token"]["symbol"],
            "name": k["base_token"]["name"] or q["base_token"]["name"],
            "contract_address": addr,
            "price_kyber": price_k,
            "price_quickswap": price_q,
            "diff_pct": round(diff_pct, 3),
            "liquidity_kyber": round(k["liquidity_usd"], 2),
            "liquidity_quickswap": round(q["liquidity_usd"], 2),
            "volume_24h_kyber": round(k["volume_24h_usd"], 2),
            "volume_24h_quickswap": round(q["volume_24h_usd"], 2),
            "txns_24h_kyber": k["txns_24h"],
            "txns_24h_quickswap": q["txns_24h"],
            "traders_24h_kyber": k["traders_24h"],
            "traders_24h_quickswap": q["traders_24h"],
            "net_profit_per_100": net_profit_100,
        })

    opportunities.sort(key=lambda x: x["diff_pct"], reverse=True)
    return opportunities


# ---------------------------------------------------------------------------
# إرسال النتائج إلى تيليجرام
# ---------------------------------------------------------------------------

def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("لم يتم ضبط TELEGRAM_BOT_TOKEN أو TELEGRAM_CHAT_ID — سيتم طباعة النتيجة فقط.")
        print(text)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    # تيليجرام يحدد طول الرسالة بـ 4096 حرف، نقسّم إن لزم
    max_len = 3800
    chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)] or [text]

    for chunk in chunks:
        try:
            resp = requests.post(url, data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }, timeout=15)
            if resp.status_code != 200:
                log.error(f"فشل إرسال رسالة تيليجرام: {resp.text}")
        except requests.RequestException as e:
            log.error(f"خطأ اتصال تيليجرام: {e}")
        time.sleep(1)


def format_opportunity_message(opp):
    return (
        f"🔎 <b>{opp['symbol']}</b> ({opp['name']})\n"
        f"📜 العقد: <code>{opp['contract_address']}</code>\n"
        f"💰 السعر KyberSwap: ${opp['price_kyber']:.8f}\n"
        f"💰 السعر QuickSwap: ${opp['price_quickswap']:.8f}\n"
        f"📊 فرق السعر: <b>{opp['diff_pct']}%</b>\n"
        f"💧 السيولة (Kyber/Quick): ${opp['liquidity_kyber']:,} / ${opp['liquidity_quickswap']:,}\n"
        f"📈 الحجم 24س (Kyber/Quick): ${opp['volume_24h_kyber']:,} / ${opp['volume_24h_quickswap']:,}\n"
        f"🔁 المعاملات 24س (Kyber/Quick): {opp['txns_24h_kyber']} / {opp['txns_24h_quickswap']}\n"
        f"👥 المتداولون 24س (Kyber/Quick): {opp['traders_24h_kyber']} / {opp['traders_24h_quickswap']}\n"
        f"✅ الربح الصافي التقديري لكل $100: <b>${opp['net_profit_per_100']}</b>\n"
        f"⚠️ تقدير تقريبي (رسوم+غاز+انزلاق تحفظي) — تحقق يدوياً قبل التنفيذ.\n"
    )


# ---------------------------------------------------------------------------
# دورة الفحص الرئيسية
# ---------------------------------------------------------------------------

def run_scan():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    log.info(f"بدء الفحص — {now}")

    kyber_pools_raw, kyber_included = fetch_all_pools(KYBER_DEX_SLUG)
    log.info(f"KyberSwap Elastic: تم جلب {len(kyber_pools_raw)} مجمع.")

    quick_pools_raw, quick_included = fetch_all_pools(QUICKSWAP_DEX_SLUG)
    log.info(f"QuickSwap v3: تم جلب {len(quick_pools_raw)} مجمع.")

    kyber_candidates = build_candidate_map(kyber_pools_raw, kyber_included, "KyberSwap Elastic")
    quick_candidates = build_candidate_map(quick_pools_raw, quick_included, "QuickSwap v3")

    log.info(f"مرشحون مستوفون للشروط — Kyber: {len(kyber_candidates)} | QuickSwap: {len(quick_candidates)}")

    opportunities = find_arbitrage_opportunities(kyber_candidates, quick_candidates)

    if not opportunities:
        msg = (
            f"📭 لا توجد فرص مطابقة لكل الشروط حالياً ({now}).\n"
            f"مرشحون على Kyber: {len(kyber_candidates)} | على QuickSwap: {len(quick_candidates)}\n"
            f"جرّب توسيع الشروط عبر متغيرات البيئة إن أردت (MIN_PRICE_DIFF_PCT وغيره)."
        )
        log.info(msg)
        send_telegram_message(msg)
        return

    header = f"🚨 <b>فرص مراجحة محتملة — Polygon</b>\n🕒 {now}\nعدد الفرص: {len(opportunities)}\n\n"
    body = "\n".join(format_opportunity_message(o) for o in opportunities[:15])
    send_telegram_message(header + body)
    log.info(f"تم إرسال {min(len(opportunities), 15)} فرصة إلى تيليجرام.")


def main():
    log.info("تشغيل ماسح المراجحة (KyberSwap Elastic ⇄ QuickSwap v3 | Polygon)")
    log.info(f"الفحص كل {SCAN_INTERVAL_MINUTES} دقيقة.")
    while True:
        try:
            run_scan()
        except Exception as e:
            log.exception(f"خطأ غير متوقع أثناء الفحص: {e}")
        time.sleep(SCAN_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()

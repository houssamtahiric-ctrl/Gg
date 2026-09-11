import requests
import asyncio
from telegram import Bot
import os

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
CHECK_INTERVAL = 30

WATCHLIST = [
    "0xfa68FB4628DFF1028CFEc22b4162FCcd1d55e376",
]

bot = Bot(token=TELEGRAM_TOKEN)

def get_prices(token_address):
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        res = requests.get(url, timeout=10)
        data = res.json()
        pairs = data.get("pairs", [])
        if not pairs:
            return None
        prices = {}
        for p in pairs:
            price = p.get("priceUsd")
            if not price:
                continue
            dex = p.get("dexId")
            liq = p.get("liquidity", {}).get("usd", 0)
            if dex not in prices or liq > prices[dex]["liq"]:
                prices[dex] = {"price": float(price), "liq": liq}
        return prices
    except Exception as e:
        print(f"Error: {e}")
        return None

async def send_alert(message):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown")
    except Exception as e:
        print(f"Telegram error: {e}")

async def check_arbitrage(token_address, token_name="Token"):
    prices = get_prices(token_address)
    if not prices:
        return
    dexes = list(prices.keys())
    if len(dexes) < 2:
        return
    for i in range(len(dexes)):
        for j in range(i + 1, len(dexes)):
            dex_a, dex_b = dexes[i], dexes[j]
            price_a = prices[dex_a]["price"]
            price_b = prices[dex_b]["price"]
            liq_a = prices[dex_a]["liq"]
            liq_b = prices[dex_b]["liq"]
            if liq_a < 10000 or liq_b < 10000:
                continue
            diff = abs(price_a - price_b) / min(price_a, price_b) * 100
            if 0.7 < diff < 2.0:
                buy_dex = dex_a if price_a < price_b else dex_b
                sell_dex = dex_b if price_a < price_b else dex_a
                buy_price = min(price_a, price_b)
                sell_price = max(price_a, price_b)
                msg = (
                    f"🚨 *فرصة مراجحة* 🚨\n"
                    f"*العملة*: {token_name}\n"
                    f"*العنوان*: `{token_address}`\n"
                    f"*المنصة A*: {dex_a} → ${price_a:.6f}\n"
                    f"*المنصة B*: {dex_b} → ${price_b:.6f}\n"
                    f"*الفرق*: {diff:.2f}%\n"
                    f"*الاتجاه*: شراء من {buy_dex}، بيع في {sell_dex}"
                )
                await send_alert(msg)

async def main():
    print("🔥 البوت يعمل...")
    while True:
        for token in WATCHLIST:
            await check_arbitrage(token)
        await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())

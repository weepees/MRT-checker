import asyncio
import os
import re
from datetime import datetime, date
from typing import List, Dict

import requests
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

URL_PAGE = "https://mano.affidea.lt/services/2/65/?cityId=138236&serviceId=140499&visitPaymentTypeId=2"

# Telegram per ENV (GitHub Actions secrets)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "fallback")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "fallback")

STATE_FILE = "state.txt"


def read_state() -> str:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return "unknown"


def write_state(state: str):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        f.write(state)


def send_telegram_message(text: str):
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    params = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    try:
        requests.get(api_url, params=params, timeout=15)
    except Exception as e:
        print(f"[ERROR] Nepavyko išsiųsti Telegram žinutės: {e}")


def parse_date_from_nuo(nuo_line: str) -> date | None:
    """
    Priima eilutę kaip 'Nuo: 2025-11-13' arba 'Nuo: 13.11.2025' ir grąžina date.
    """
    s = nuo_line.strip()
    # ISO YYYY-MM-DD
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        y, mo, d = map(int, m.groups())
        return date(y, mo, d)
    # DD.MM.YYYY
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
    if m:
        d, mo, y = map(int, m.groups())
        return date(y, mo, d)
    return None


async def extract_cards(page) -> List[Dict]:
    """
    Grąžina sąrašą kortelių:
    {
      'address': 'Vilniaus Antakalnio diagnostikos centras, ... Vilnius',
      'price': 'Kaina: 320.00 €' arba '–',
      'nuo': 'Nuo: 2025-11-13' arba '–',
      'nuo_date': datetime.date | None,
      'active': True/False
    }
    """
    # imame visas “korteles”, kuriose yra Registruotis mygtukas
    cards = await page.query_selector_all("div:has(button:has-text('Registruotis'))")
    results: List[Dict] = []

    for card in cards:
        text = (await card.inner_text()).strip()
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

        address = next((l for l in lines if "Vilnius" in l), "–")
        price = next((l for l in lines if l.startswith("Kaina")), "–")
        nuo = next((l for l in lines if l.startswith("Nuo:")), "–")
        nuo_dt = parse_date_from_nuo(nuo) if nuo != "–" else None

        btn = await card.query_selector("button:has-text('Registruotis')")
        disabled = await btn.is_disabled() if btn else True

        results.append({
            "address": address,
            "price": price,
            "nuo": nuo,
            "nuo_date": nuo_dt,
            "active": not disabled,
        })

    return results


def signature_for_active(cards: List[Dict]) -> str:
    """
    Sudarom “parašą” iš AKTYVIŲ kortelių, kad žinotume ar kas pasikeitė:
    address|YYYY-MM-DD, surūšiuota ir sujungta “||”.
    """
    parts = []
    for c in cards:
        if c["active"]:
            d = c["nuo_date"].isoformat() if c["nuo_date"] else c["nuo"]
            parts.append(f"{c['address']}|{d}")
    if not parts:
        return "inactive"
    parts.sort()
    return "active:" + "||".join(parts)


async def check_and_collect():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(URL_PAGE, wait_until="load", timeout=60000)
        except TimeoutError:
            print("[WARN] Page.goto timeout – tęsiu su tuo, kas užsikrovė")
        await page.wait_for_timeout(4000)

        cards = await extract_cards(page)
        await browser.close()

    has_active = any(c["active"] for c in cards)
    return has_active, cards


async def main():
    print(f"[INFO] Tikrinu {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ...")

    has_active, cards = await check_and_collect()

    # sudarom dabartinį “parašą”
    sig_now = signature_for_active(cards)
    prev = read_state()

    # išvestis į konsolę
    print(f"[DEBUG] prev_state={prev}")
    print(f"[DEBUG] now_state={sig_now}")

    # nusprendžiam ar siųsti
    should_notify = (sig_now != prev)

    if should_notify:
        if sig_now.startswith("active:"):
            # surandam artimiausią datą ir suformuojam gražią žinutę
            active_cards = [c for c in cards if c["active"]]
            # artimiausia:
            earliest = min(
                (c for c in active_cards if c["nuo_date"] is not None),
                key=lambda x: x["nuo_date"],
                default=None
            )

            header = "🟢 AFFIDEA: atsirado laisvų vietų!"
            if earliest:
                header += f"\nArtimiausia data: {earliest['nuo_date'].isoformat()}"

            # visų aktyvių išvardinimas
            blocks = []
            for c in active_cards:
                blocks.append(
                    f"{c['address']}\n"
                    f"{c['price']}\n"
                    f"{c['nuo']}"
                )

            msg = header + "\n\n" + "\n\n".join(blocks) + f"\n\n👉 {URL_PAGE}"
            send_telegram_message(msg)

        else:
            # perėjimas į “inactive”
            if prev not in ("unknown", ""):
                send_telegram_message("🔴 AFFIDEA: nebeliko aktyvių REGISTRUOTIS mygtukų.")

        write_state(sig_now)

    # informacinė eilutė
    print(f"[INFO] Būsena: {'active' if has_active else 'inactive'}")


if __name__ == "__main__":
    asyncio.run(main())

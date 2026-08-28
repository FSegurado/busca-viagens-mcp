"""Scraper (Playwright) para o Google Flights.

IMPORTANTE: seletores baseados em padrões conhecidos da UI do Google Flights
(aria-labels em inglês, forçado via hl=en). Como este script roda apenas no
runner do GitHub Actions -- sem acesso a partir do ambiente de
desenvolvimento -- é esperado que precise de ajustes após os primeiros
execuções reais; por isso cada etapa loga o que está fazendo e, em caso de
falha, salva screenshot + HTML em artifacts/google_flights/ para inspeção.
"""
import re
from datetime import date
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout

from config import ADULTS, DEPART_DATE, DEST_CITY, ORIGIN_CITY, RETURN_DATE

BASE_URL = "https://www.google.com/travel/flights?hl=en&curr=BRL&gl=BR"
DEBUG_DIR = Path("artifacts/google_flights")


def _log(msg: str) -> None:
    print(f"[google_flights] {msg}")


def _dump(page, tag: str) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(DEBUG_DIR / f"{tag}.png"), full_page=True)
        (DEBUG_DIR / f"{tag}.html").write_text(page.content(), encoding="utf-8")
        _log(f"debug salvo em {DEBUG_DIR}/{tag}.(png|html)")
    except Exception as exc:
        _log(f"falha ao salvar debug: {exc}")


def _accept_cookies(page) -> None:
    for name in ["Accept all", "I agree", "Aceitar tudo"]:
        try:
            page.get_by_role("button", name=re.compile(re.escape(name), re.I)).click(timeout=3000)
            _log(f"cookie banner fechado ('{name}')")
            return
        except PWTimeout:
            continue


def _fill_airport(page, field_label: str, city: str) -> bool:
    try:
        box = page.get_by_role("combobox", name=re.compile(field_label, re.I)).first
        box.click(timeout=8000)
        box.fill(city)
        page.wait_for_timeout(1500)
        page.get_by_role("option").first.click(timeout=8000)
        _log(f"campo '{field_label}' preenchido com '{city}'")
        return True
    except PWTimeout:
        _log(f"não consegui preencher o campo '{field_label}' com '{city}'")
        return False


def _set_passengers(page, adults: int) -> None:
    try:
        page.get_by_role("button", name=re.compile(r"passenger", re.I)).first.click(timeout=5000)
    except PWTimeout:
        _log("seletor de passageiros não encontrado, seguindo com valor padrão")
        return
    try:
        add_adult = page.get_by_role("button", name=re.compile(r"Add adult", re.I))
        current = 1
        while current < adults:
            add_adult.click(timeout=3000)
            current += 1
        page.get_by_role("button", name=re.compile(r"^Done$", re.I)).click(timeout=5000)
        _log(f"passageiros ajustado para {adults} adulto(s)")
    except PWTimeout:
        _log("não consegui ajustar o número de passageiros, seguindo com valor padrão")


def _months_ahead(target_iso: str) -> int:
    today = date.today()
    y, m, _ = (int(x) for x in target_iso.split("-"))
    return max((y - today.year) * 12 + (m - today.month), 0)


def _pick_date(page, iso_date: str, field_label: str) -> bool:
    y, m, d = (int(x) for x in iso_date.split("-"))
    try:
        page.get_by_role("textbox", name=re.compile(field_label, re.I)).first.click(timeout=8000)
    except PWTimeout:
        _log(f"não consegui abrir o calendário via campo '{field_label}'")
        return False

    clicks_needed = _months_ahead(iso_date)
    for _ in range(clicks_needed):
        try:
            page.get_by_role("button", name=re.compile(r"Next month|Go to next month", re.I)).first.click(timeout=4000)
            page.wait_for_timeout(300)
        except PWTimeout:
            _log("botão 'próximo mês' não encontrado durante navegação do calendário")
            return False

    day_pattern = re.compile(rf"\b{d}\b.*\b{y}\b", re.I)
    try:
        page.get_by_role("button", name=day_pattern).first.click(timeout=6000)
        _log(f"data {iso_date} selecionada no campo '{field_label}'")
        return True
    except PWTimeout:
        _log(f"não encontrei o dia {iso_date} no calendário")
        return False


def buscar(playwright) -> dict | None:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(locale="en-US", timezone_id="America/Sao_Paulo")
    page = context.new_page()

    try:
        _log(f"abrindo {BASE_URL}")
        page.goto(BASE_URL, timeout=45000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        _accept_cookies(page)

        ok_origem = _fill_airport(page, "Where from", ORIGIN_CITY)
        ok_destino = _fill_airport(page, "Where to", DEST_CITY)
        if not (ok_origem and ok_destino):
            _dump(page, "falha_preenchimento_aeroportos")
            return None

        _set_passengers(page, ADULTS)

        ok_ida = _pick_date(page, DEPART_DATE, "Departure")
        ok_volta = _pick_date(page, RETURN_DATE, "Return")
        if not (ok_ida and ok_volta):
            _dump(page, "falha_selecao_datas")
            return None

        try:
            page.get_by_role("button", name=re.compile(r"^Done$", re.I)).click(timeout=3000)
        except PWTimeout:
            pass

        try:
            page.get_by_role("button", name=re.compile(r"^Search$", re.I)).click(timeout=6000)
        except PWTimeout:
            _log("botão 'Search' não encontrado -- talvez a busca já tenha atualizado sozinha")

        _log("aguardando resultados carregarem...")
        page.wait_for_selector("text=/R\\$\\s?[\\d.,]+/", timeout=30000)
        page.wait_for_timeout(2500)

        candidatos = page.locator('[role="listitem"]')
        n = candidatos.count()
        _log(f"{n} itens de resultado encontrados na lista")

        precos = []
        texto_fonte = ""
        if n > 0:
            for i in range(min(n, 20)):
                texto_fonte += " " + candidatos.nth(i).inner_text()
        else:
            texto_fonte = page.inner_text("body")

        precos = [
            float(p.replace(".", "").replace(",", "."))
            for p in re.findall(r"R\$\s?([\d.,]+)", texto_fonte)
        ]
        precos = [p for p in precos if p > 50]  # filtra ruído tipo taxas pequenas

        if not precos:
            _log("nenhum preço em R$ encontrado no texto dos resultados")
            _dump(page, "sem_preco")
            return None

        menor = min(precos)
        por_passageiro = "per traveler" in texto_fonte.lower() or "por passageiro" in texto_fonte.lower()
        preco_por_adulto = menor if por_passageiro else round(menor / ADULTS, 2)
        preco_total = round(preco_por_adulto * ADULTS, 2)

        _log(f"preço mínimo capturado: R$ {menor:.2f} (interpretado como {'por passageiro' if por_passageiro else 'total, dividido por 2'})")

        return {
            "preco_por_adulto": round(preco_por_adulto, 2),
            "preco_total_2_adultos": preco_total,
            "companhia_voo": "Não especificado (ver link)",
            "fonte": "Google Flights (scraping real)",
            "link": page.url,
            "observacoes": (
                "Preço extraído via scraping real (Playwright) da página de resultados do Google "
                f"Flights, com origem/destino/datas/{ADULTS} adultos preenchidos na própria UI. "
                f"Interpretação do valor exibido como preço {'por passageiro' if por_passageiro else 'total (dividido por 2 adultos)'} "
                "com base no texto da página; confirme no link antes de comprar."
            ),
        }
    except Exception as exc:
        _log(f"erro inesperado: {exc}")
        try:
            _dump(page, "erro_inesperado")
        except Exception:
            pass
        return None
    finally:
        context.close()
        browser.close()

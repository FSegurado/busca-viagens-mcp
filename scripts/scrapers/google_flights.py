"""Scraper (Playwright) para o Google Flights.

IMPORTANTE: seletores baseados em padrões conhecidos da UI do Google Flights
(aria-labels em inglês, forçado via hl=en). Como este script roda apenas no
runner do GitHub Actions -- sem acesso a partir do ambiente de
desenvolvimento -- é esperado que precise de ajustes após as primeiras
execuções reais. Por isso cada etapa loga o que está fazendo e, em caso de
falha, chama debug_utils.diagnostico() para imprimir nos LOGS do job (não em
artifact -- o storage de artifacts não é alcançável a partir daqui) os
elementos interativos realmente presentes na página.
"""
import re
import sys
from datetime import date
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout

from config import ADULTS, DEPART_DATE, DEST_CITY, ORIGIN_CITY, RETURN_DATE
from scrapers import debug_utils

BASE_URL = "https://www.google.com/travel/flights?hl=en&curr=BRL&gl=BR"
DEBUG_DIR = Path("artifacts/google_flights")


def _log(msg: str) -> None:
    print(f"[google_flights] {msg}", flush=True)


def _fail(page, tag: str) -> None:
    debug_utils.dump(page, DEBUG_DIR, tag, _log)
    debug_utils.diagnostico(page, _log)


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
        box.click(timeout=12000)
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


def _select_dates(page, depart_iso: str, return_iso: str) -> bool:
    """Abre o calendário e seleciona ida/volta.

    Baseado em diagnóstico real: o calendário do Google Flights mostra dois
    meses simultaneamente e as células de dia são botões cujo nome
    acessível é literalmente "{dia}\\n{preço}" (sem mês/ano). Não existe um
    botão "Next month" clicável por role -- a navegação de mês é feita via
    teclado (PageDown), seguindo o padrão ARIA de date pickers.
    """
    try:
        page.get_by_role("textbox", name=re.compile("Departure", re.I)).first.click(timeout=12000)
    except PWTimeout:
        _log("não consegui abrir o calendário via campo 'Departure'")
        return False

    # como o calendário mostra 2 meses de uma vez, 1 PageDown já avança a
    # janela em 1 mês -- por isso -1 em relação à distância total de meses.
    paginas = max(_months_ahead(depart_iso) - 1, 0)
    for _ in range(paginas):
        page.keyboard.press("PageDown")
        page.wait_for_timeout(400)
    if paginas:
        _log(f"calendário paginado {paginas}x via teclado (PageDown) em direção a {depart_iso}")

    dia_ida = int(depart_iso.split("-")[2])
    dia_volta = int(return_iso.split("-")[2])

    padrao_ida = re.compile(rf"^{dia_ida}\D")
    try:
        page.get_by_role("button", name=padrao_ida).first.click(timeout=8000)
        _log(f"dia de ida ({depart_iso}) selecionado")
    except PWTimeout:
        _log(f"não encontrei o botão do dia de ida ({dia_ida}) no calendário após paginar")
        return False

    padrao_volta = re.compile(rf"^{dia_volta}\D")
    try:
        page.get_by_role("button", name=padrao_volta).first.click(timeout=8000)
        _log(f"dia de volta ({return_iso}) selecionado")
    except PWTimeout:
        _log(f"não encontrei o botão do dia de volta ({dia_volta}) no calendário")
        return False

    return True


def buscar(playwright) -> dict | None:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(locale="en-US", timezone_id="America/Sao_Paulo")
    page = context.new_page()

    try:
        _log(f"abrindo {BASE_URL}")
        page.goto(BASE_URL, timeout=45000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        _log(f"página carregada, título inicial: {page.title()!r}")
        _accept_cookies(page)
        page.wait_for_timeout(1000)

        ok_origem = _fill_airport(page, "Where from", ORIGIN_CITY)
        ok_destino = _fill_airport(page, "Where to", DEST_CITY)
        if not (ok_origem and ok_destino):
            _log("falha ao preencher aeroportos -- rodando diagnóstico")
            _fail(page, "falha_preenchimento_aeroportos")
            return None

        _set_passengers(page, ADULTS)

        if not _select_dates(page, DEPART_DATE, RETURN_DATE):
            _fail(page, "falha_selecao_datas")
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
            _fail(page, "sem_preco")
            return None

        menor = min(precos)
        por_passageiro = "per traveler" in texto_fonte.lower() or "por passageiro" in texto_fonte.lower()
        preco_por_adulto = menor if por_passageiro else round(menor / ADULTS, 2)
        preco_total = round(preco_por_adulto * ADULTS, 2)

        _log(
            f"preço mínimo capturado: R$ {menor:.2f} "
            f"(interpretado como {'por passageiro' if por_passageiro else 'total, dividido por 2'})"
        )

        return {
            "preco_por_adulto": round(preco_por_adulto, 2),
            "preco_total_2_adultos": preco_total,
            "companhia_voo": "Não especificado (ver link)",
            "fonte": "Google Flights (scraping real)",
            "link": page.url,
            "observacoes": (
                "Preço extraído via scraping real (Playwright) da página de resultados do Google "
                f"Flights, com origem/destino/datas/{ADULTS} adultos preenchidos na própria UI. "
                f"Interpretação do valor exibido como preço "
                f"{'por passageiro' if por_passageiro else 'total (dividido por 2 adultos)'} "
                "com base no texto da página; confirme no link antes de comprar."
            ),
        }
    except Exception as exc:
        _log(f"erro inesperado: {exc!r}")
        try:
            _fail(page, "erro_inesperado")
        except Exception:
            pass
        return None
    finally:
        sys.stdout.flush()
        context.close()
        browser.close()

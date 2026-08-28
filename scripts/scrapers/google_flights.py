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
import calendar
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
    # o campo é um widget de autocomplete customizado, não um <input> puro:
    # .fill() nem sempre dispara os listeners internos que abrem a lista de
    # sugestões. Digitar caractere a caractere (press_sequentially) simula
    # teclado de verdade e é bem mais confiável aqui.
    try:
        box = page.get_by_role("combobox", name=re.compile(field_label, re.I)).first
        box.click(timeout=12000)
    except PWTimeout:
        _log(f"não consegui clicar no campo '{field_label}'")
        return False
    try:
        box.press_sequentially(city, delay=80)
    except Exception as exc:
        _log(f"não consegui digitar em '{field_label}': {exc}")
        return False
    try:
        page.wait_for_timeout(1200)
        page.get_by_role("option").first.click(timeout=8000)
        _log(f"campo '{field_label}' preenchido com '{city}'")
        return True
    except PWTimeout:
        _log(f"digitei '{city}' em '{field_label}' mas nenhuma sugestão apareceu para clicar")
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


def _occurrence_index(today: date, target_iso: str) -> int:
    """Calcula em qual ocorrência (0-based) do dígito do dia está o botão certo.

    O calendário do Google Flights ACUMULA meses visíveis (não é uma janela
    deslizante de 2 meses) -- cada PageDown revela mais um mês inteiro (1 a
    31) além dos já mostrados, e o mês atual só mostra dias a partir de
    hoje. Como o nome acessível do botão de dia não inclui mês/ano, "26" se
    repete uma vez por mês visível; a ocorrência certa é a que corresponde
    ao mês/ano alvo, contando quantos meses anteriores também têm esse dia.
    """
    ty, tm, td = (int(x) for x in target_iso.split("-"))
    idx = 0
    y, m = today.year, today.month
    while (y, m) != (ty, tm):
        is_mes_atual = (y == today.year and m == today.month)
        dias_no_mes = calendar.monthrange(y, m)[1]
        if td <= dias_no_mes and (not is_mes_atual or td >= today.day):
            idx += 1
        m += 1
        if m == 13:
            m = 1
            y += 1
    return idx


def _fmt_us(iso: str) -> str:
    y, m, d = (int(x) for x in iso.split("-"))
    return f"{m}/{d}/{y}"


def _select_dates_by_typing(page, depart_iso: str, return_iso: str) -> bool:
    """Estratégia primária: digitar a data direto nos <input> Departure/Return.

    Mais robusto do que navegar o calendário e clicar em células (ver
    _select_dates_by_calendar) -- evita toda a complicação de paginação
    assíncrona e ambiguidade de dias repetidos entre meses.
    """
    try:
        campo_ida = page.get_by_role("textbox", name=re.compile("Departure", re.I)).first
        campo_ida.click(timeout=12000)
        campo_ida.press_sequentially(_fmt_us(depart_iso), delay=60)
        page.wait_for_timeout(500)

        campo_volta = page.get_by_role("textbox", name=re.compile("Return", re.I)).first
        campo_volta.click(timeout=8000)
        campo_volta.press_sequentially(_fmt_us(return_iso), delay=60)
        page.wait_for_timeout(500)
        page.keyboard.press("Enter")
        page.wait_for_timeout(1000)
    except Exception as exc:
        _log(f"digitação direta de datas falhou: {exc}")
        return False

    # confirma que os campos realmente refletem as datas digitadas
    try:
        texto_ida = page.get_by_role("textbox", name=re.compile("Departure", re.I)).first.input_value()
        texto_volta = page.get_by_role("textbox", name=re.compile("Return", re.I)).first.input_value()
    except Exception:
        texto_ida = texto_volta = ""
    _log(f"após digitação: campo ida={texto_ida!r} campo volta={texto_volta!r}")

    dia_ida = str(int(depart_iso.split('-')[2]))
    dia_volta = str(int(return_iso.split('-')[2]))
    return dia_ida in texto_ida and dia_volta in texto_volta


def _select_dates_by_calendar(page, depart_iso: str, return_iso: str) -> bool:
    """Fallback: navega o calendário via teclado e clica nas células de dia.

    Baseado em diagnóstico real: os botões de dia têm nome acessível
    "{dia}\\n{preço}" (sem mês/ano) e o calendário ACUMULA meses (cada
    PageDown soma mais um mês, sem descartar os anteriores) -- por isso
    calculamos em qual ocorrência (.nth) do dígito do dia cai o mês certo.
    """
    try:
        page.get_by_role("textbox", name=re.compile("Departure", re.I)).first.click(timeout=12000)
    except PWTimeout:
        _log("não consegui abrir o calendário via campo 'Departure'")
        return False

    paginas = _months_ahead(depart_iso) + 1
    for _ in range(paginas):
        page.keyboard.press("PageDown")
        page.wait_for_timeout(1500)
    if paginas:
        _log(f"calendário paginado {paginas}x via teclado (PageDown) em direção a {depart_iso}")
    page.wait_for_timeout(2000)

    hoje = date.today()
    dia_ida = int(depart_iso.split("-")[2])
    dia_volta = int(return_iso.split("-")[2])

    idx_ida = _occurrence_index(hoje, depart_iso)
    padrao_ida = re.compile(rf"^{dia_ida}(\D|$)")
    _log(f"clicando na ocorrência #{idx_ida} do dia {dia_ida} (deve corresponder a {depart_iso})")
    try:
        page.get_by_role("button", name=padrao_ida).nth(idx_ida).click(timeout=10000)
        _log(f"dia de ida ({depart_iso}) selecionado")
    except PWTimeout:
        _log(f"não encontrei a ocorrência #{idx_ida} do dia de ida ({dia_ida}) no calendário após paginar")
        return False

    idx_volta = _occurrence_index(hoje, return_iso)
    padrao_volta = re.compile(rf"^{dia_volta}(\D|$)")
    _log(f"clicando na ocorrência #{idx_volta} do dia {dia_volta} (deve corresponder a {return_iso})")
    try:
        page.get_by_role("button", name=padrao_volta).nth(idx_volta).click(timeout=10000)
        _log(f"dia de volta ({return_iso}) selecionado")
    except PWTimeout:
        _log(f"não encontrei a ocorrência #{idx_volta} do dia de volta ({dia_volta}) no calendário")
        return False

    return True


def _select_dates(page, depart_iso: str, return_iso: str) -> bool:
    if _select_dates_by_typing(page, depart_iso, return_iso):
        _log("datas selecionadas via digitação direta nos campos")
        return True
    _log("digitação direta não confirmou as datas -- tentando fallback via calendário")
    return _select_dates_by_calendar(page, depart_iso, return_iso)


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

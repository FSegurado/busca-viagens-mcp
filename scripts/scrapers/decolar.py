"""Scraper (Playwright) para o Decolar.

Estratégia em duas camadas, do mais preciso ao mais confiável:

1. Tenta abrir a página da rota GYN->FLN, preencher datas exatas e número de
   adultos na própria UI, deixar o site navegar até a página de resultados e
   extrair o menor preço de lá (preço específico das datas pedidas).
2. Se qualquer etapa da camada 1 falhar (seletor mudou, captcha, etc.), cai
   para extrair o preço "a partir de R$X" que o Decolar expõe no <title> /
   texto da própria página da rota -- um piso genérico (não específico das
   datas), mas historicamente estável e fácil de confirmar.

Se as duas falharem, retorna None e loga o motivo. O diagnóstico (elementos
interativos reais da página) vai para os LOGS do job via debug_utils --
artifacts de screenshot não são alcançáveis fora do runner do Actions.
"""
import re
import sys
from datetime import date
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright_stealth import stealth_sync

from config import ADULTS, DEPART_DATE, RETURN_DATE
from scrapers import debug_utils

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)

ROUTE_URL = (
    "https://www.decolar.com/passagens-aereas/gyn/fln/"
    "passagens-aereas-para-florianopolis-saindo-de-goiania"
)
DEBUG_DIR = Path("artifacts/decolar")


def _log(msg: str) -> None:
    print(f"[decolar] {msg}", flush=True)


def _fail(page, tag: str) -> None:
    debug_utils.dump(page, DEBUG_DIR, tag, _log)
    debug_utils.diagnostico(page, _log)


def _accept_cookies(page) -> None:
    for name in ["Aceitar", "Aceitar todos", "Concordo", "Accept"]:
        try:
            page.get_by_role("button", name=re.compile(re.escape(name), re.I)).click(timeout=3000)
            _log(f"cookie banner fechado ('{name}')")
            return
        except PWTimeout:
            continue


def _months_ahead(target_iso: str) -> int:
    today = date.today()
    y, m, _ = (int(x) for x in target_iso.split("-"))
    return max((y - today.year) * 12 + (m - today.month), 0)


def _pick_dates_and_search(page) -> bool:
    """Tenta preencher datas exatas + adultos e disparar a busca. Best effort."""
    try:
        page.get_by_role("button", name=re.compile(r"data|ida.*volta|calend", re.I)).first.click(timeout=8000)
    except PWTimeout:
        _log("não encontrei o campo de datas para abrir o calendário")
        return False

    for iso in (DEPART_DATE, RETURN_DATE):
        y, m, d = (int(x) for x in iso.split("-"))
        clicks = _months_ahead(iso) if iso == DEPART_DATE else 0
        for _ in range(clicks):
            try:
                page.get_by_role("button", name=re.compile(r"pr[oó]ximo m[eê]s|next month", re.I)).first.click(timeout=4000)
                page.wait_for_timeout(300)
            except PWTimeout:
                _log("botão de próximo mês não encontrado no calendário do Decolar")
                return False
        try:
            page.get_by_role("button", name=re.compile(rf"^{d}$"), exact=False).first.click(timeout=6000)
        except PWTimeout:
            _log(f"não encontrei o dia {iso} no calendário do Decolar")
            return False

    try:
        page.get_by_role("button", name=re.compile(r"buscar|pesquisar|search", re.I)).first.click(timeout=6000)
    except PWTimeout:
        _log("botão de busca não encontrado após selecionar datas")
        return False

    return True


def _extract_price_from_results(page):
    try:
        page.wait_for_selector("text=/R\\$\\s?[\\d.,]+/", timeout=25000)
    except PWTimeout:
        return None
    page.wait_for_timeout(2000)
    texto = page.inner_text("body")
    precos = [
        float(p.replace(".", "").replace(",", "."))
        for p in re.findall(r"R\$\s?([\d.,]+)", texto)
    ]
    precos = [p for p in precos if p > 50]
    return min(precos) if precos else None


def _extract_price_from_title(page):
    titulo = page.title()
    m = re.search(r"R\$\s?([\d.,]+)", titulo)
    if not m:
        return None
    return float(m.group(1).replace(".", "").replace(",", "."))


def buscar(playwright) -> dict | None:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        locale="pt-BR",
        timezone_id="America/Sao_Paulo",
        user_agent=USER_AGENT,
        viewport={"width": 1366, "height": 900},
    )
    page = context.new_page()
    stealth_sync(page)

    try:
        _log(f"abrindo {ROUTE_URL}")
        page.goto(ROUTE_URL, timeout=45000, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except PWTimeout:
            _log("networkidle não atingido em 20s, seguindo mesmo assim")
        page.wait_for_timeout(4000)
        _log(f"página carregada, título inicial: {page.title()!r}")
        _log(f"tamanho do HTML carregado: {len(page.content())} caracteres")
        _accept_cookies(page)
        page.wait_for_timeout(1000)

        preco_exato = None
        if _pick_dates_and_search(page):
            preco_exato = _extract_price_from_results(page)
        else:
            _log("busca com datas exatas falhou na etapa de UI -- rodando diagnóstico")
            _fail(page, "falha_ui_datas")

        if preco_exato:
            preco_por_adulto = round(preco_exato, 2)
            _log(f"preço específico das datas capturado nos resultados: R$ {preco_por_adulto:.2f}/adulto")
            return {
                "preco_por_adulto": preco_por_adulto,
                "preco_total_2_adultos": round(preco_por_adulto * ADULTS, 2),
                "companhia_voo": "Não especificado (ver link)",
                "fonte": "Decolar (scraping real, datas exatas)",
                "link": page.url,
                "observacoes": (
                    "Preço extraído via scraping real (Playwright) da página de resultados do "
                    f"Decolar, com datas {DEPART_DATE}/{RETURN_DATE} e {ADULTS} adultos preenchidos "
                    "na própria UI do site. Confirme no link antes de comprar."
                ),
            }

        _log("tentando piso genérico do <title> da página da rota")

        page2 = context.new_page()
        stealth_sync(page2)
        page2.goto(ROUTE_URL, timeout=30000, wait_until="domcontentloaded")
        page2.wait_for_timeout(3000)
        preco_piso = _extract_price_from_title(page2)
        link_piso = page2.url
        if not preco_piso:
            _fail(page2, "fallback_sem_preco_no_title")
        page2.close()

        if not preco_piso:
            _log("também não encontrei preço no <title> -- desistindo desta fonte")
            return None

        preco_por_adulto = round(preco_piso, 2)
        _log(f"piso genérico capturado: R$ {preco_por_adulto:.2f}/adulto")
        return {
            "preco_por_adulto": preco_por_adulto,
            "preco_total_2_adultos": round(preco_por_adulto * ADULTS, 2),
            "companhia_voo": "Não especificado",
            "fonte": "Decolar (piso genérico da rota)",
            "link": link_piso,
            "observacoes": (
                "A busca com datas exatas na UI do Decolar falhou nesta execução (ver logs do job "
                "para o diagnóstico dos elementos da página). Valor obtido é o piso 'a partir de "
                "R$X' exibido no título da página da rota GYN-FLN -- genérico, NÃO específico das "
                f"datas {DEPART_DATE}/{RETURN_DATE} nem do número de passageiros. Confirme no link "
                "antes de comprar."
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

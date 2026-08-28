"""Orquestra a coleta de preços (Google Flights + Decolar), grava no CSV e
atualiza o resumo.md. Executado pelo workflow do GitHub Actions.
"""
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))

import csv_utils  # noqa: E402
from config import CSV_PATH, GOAL_PRICE_PER_ADULT, SUMMARY_PATH  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from scrapers import decolar, google_flights  # noqa: E402


def _rodar(nome, fn, playwright, log):
    print(f"== {nome} ==")
    try:
        resultado = fn(playwright)
    except Exception as exc:  # nunca deixa uma fonte derrubar a outra
        print(f"[{nome}] erro inesperado não tratado: {exc}")
        resultado = None
    if resultado:
        print(f"[{nome}] OK: R$ {resultado['preco_por_adulto']:.2f} / adulto ({resultado['fonte']})")
    else:
        log.append(f"{nome}: sem resultado válido nesta execução (ver logs acima).")
    return resultado


def main() -> None:
    tz = ZoneInfo("America/Sao_Paulo")
    now = datetime.now(tz)

    falhas = []
    resultados = []

    with sync_playwright() as p:
        r1 = _rodar("Google Flights", google_flights.buscar, p, falhas)
        if r1:
            resultados.append(r1)
        r2 = _rodar("Decolar", decolar.buscar, p, falhas)
        if r2:
            resultados.append(r2)

    summary_path = Path("job_summary.md")

    if not resultados:
        print("Nenhuma fonte retornou preço válido nesta execução. Nada será gravado no CSV.")
        summary_path.write_text(
            "### ⚠️ Falha na coleta de preços\n\n"
            + "\n".join(f"- {f}" for f in falhas)
            + "\n\nNenhum dado novo foi adicionado ao histórico nesta execução. "
            "Veja os artifacts de debug (screenshots/HTML) anexados a este run.\n",
            encoding="utf-8",
        )
        return

    melhor = min(resultados, key=lambda r: r["preco_por_adulto"])
    outros = [r for r in resultados if r is not melhor]

    obs = melhor["observacoes"]
    if outros:
        obs += " | Outras fontes consultadas nesta execução: " + "; ".join(
            f"{o['fonte']} R$ {o['preco_por_adulto']:.2f}/adulto" for o in outros
        )
    if falhas:
        obs += " | Falharam nesta execução: " + "; ".join(falhas)

    linha = {
        "data_consulta": now.strftime("%Y-%m-%d"),
        "horario_consulta": now.strftime("%H:%M"),
        "preco_por_adulto": f"{melhor['preco_por_adulto']:.2f}",
        "preco_total_2_adultos": f"{melhor['preco_total_2_adultos']:.2f}",
        "companhia_voo": melhor["companhia_voo"],
        "fonte": melhor["fonte"],
        "link": melhor["link"],
        "observacoes": obs,
    }

    csv_utils.append_row(CSV_PATH, linha)
    stats = csv_utils.compute_stats(CSV_PATH)
    csv_utils.render_resumo(SUMMARY_PATH, stats, linha, GOAL_PRICE_PER_ADULT, now)

    preco = float(linha["preco_por_adulto"])
    atingiu_meta = preco < GOAL_PRICE_PER_ADULT
    print(f"Registrado: R$ {preco:.2f} / adulto via {linha['fonte']}")

    summary_path.write_text(
        (
            f"### {'🎯 Meta atingida!' if atingiu_meta else '📊 Preço registrado'}\n\n"
            f"- **Preço:** R$ {csv_utils.fmt_brl(preco)} / adulto "
            f"(R$ {csv_utils.fmt_brl(float(linha['preco_total_2_adultos']))} total)\n"
            f"- **Fonte:** {linha['fonte']}\n"
            f"- **Link:** {linha['link']}\n"
            f"- **Média histórica:** R$ {csv_utils.fmt_brl(stats['media'])} ({stats['total']} consultas)\n"
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

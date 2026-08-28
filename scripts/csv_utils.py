"""Leitura/escrita do historico_precos.csv e geração do resumo.md."""
import csv
from pathlib import Path
from statistics import mean

from config import CSV_HEADER


def fmt_brl(value: float) -> str:
    """Formata um número no padrão brasileiro: milhar com ponto, decimal com vírgula."""
    s = f"{value:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def ensure_header(path: str) -> None:
    p = Path(path)
    if not p.exists():
        with p.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(CSV_HEADER)


def append_row(path: str, row: dict) -> None:
    ensure_header(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=CSV_HEADER).writerow(row)


def compute_stats(path: str) -> dict:
    with open(path, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("preco_por_adulto")]

    precos = [float(r["preco_por_adulto"]) for r in rows]
    menor_row = min(rows, key=lambda r: float(r["preco_por_adulto"]))
    maior_row = max(rows, key=lambda r: float(r["preco_por_adulto"]))

    return {
        "total": len(rows),
        "media": mean(precos),
        "menor": float(menor_row["preco_por_adulto"]),
        "menor_data": menor_row["data_consulta"],
        "menor_link": menor_row.get("link", ""),
        "maior": float(maior_row["preco_por_adulto"]),
        "maior_data": maior_row["data_consulta"],
    }


def render_resumo(path: str, stats: dict, ultima_linha: dict, meta: float, now) -> None:
    preco_atual = float(ultima_linha["preco_por_adulto"])
    meta_atingida = preco_atual < meta

    linhas = [
        "# Resumo — Monitoramento de Preços GYN → FLN (26 a 30/11/2026, 2 adultos)",
        "",
        f"- **Preço médio por adulto (histórico completo):** R$ {fmt_brl(stats['media'])}",
        f"- **Preço mais baixo já encontrado:** R$ {fmt_brl(stats['menor'])} (em {stats['menor_data']})"
        + (f" — [ver oferta/busca]({stats['menor_link']})" if stats["menor_link"] else ""),
        f"- **Preço mais alto já encontrado:** R$ {fmt_brl(stats['maior'])} (em {stats['maior_data']})",
        f"- **Número total de consultas registradas:** {stats['total']}",
        f"- **Link da consulta mais recente:** {ultima_linha['link']}",
        f"- **Última atualização:** {now.strftime('%Y-%m-%d %H:%M')} (horário de Brasília)",
        "",
        "## Meta do usuário",
        "",
    ]

    if meta_atingida:
        linhas.append(
            f"🎯 **META ATINGIDA nesta consulta**: R$ {fmt_brl(preco_atual)} por adulto, abaixo dos "
            f"R$ {fmt_brl(meta)} desejados! Companhia: {ultima_linha['companhia_voo']}. "
            f"Fonte: {ultima_linha['fonte']}. Link: {ultima_linha['link']}"
        )
    else:
        linhas.append(
            f"⚠️ Meta de menos de R$ {fmt_brl(meta)} por adulto **não atingida** nesta consulta "
            f"(R$ {fmt_brl(preco_atual)} encontrado via {ultima_linha['fonte']})."
        )

    linhas += [
        "",
        "Dados coletados via **scraping real (Playwright)** rodando em GitHub Actions, direto do "
        "Google Flights e/ou Decolar — sem intermediação de busca textual. Consulte a coluna "
        "`observacoes` no CSV para detalhes de cada execução (inclusive quando alguma fonte falhou).",
        "",
        "*Este arquivo é atualizado automaticamente a cada consulta registrada em `historico_precos.csv`.*",
    ]

    Path(path).write_text("\n".join(linhas) + "\n", encoding="utf-8")

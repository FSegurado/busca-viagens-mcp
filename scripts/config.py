"""Parâmetros fixos da busca de passagens GYN -> FLN."""
from pathlib import Path

# absoluto e independente do cwd -- o workflow roda este script com
# working-directory: scripts, então um caminho relativo tipo
# "historico_precos.csv" resolveria para scripts/historico_precos.csv
# (um arquivo novo, não o real na raiz do repo) em vez de atualizar o CSV
# de verdade.
REPO_ROOT = Path(__file__).resolve().parent.parent

ORIGIN_CODE = "GYN"
ORIGIN_CITY = "Goiânia"
DEST_CODE = "FLN"
DEST_CITY = "Florianópolis"

DEPART_DATE = "2026-11-26"  # YYYY-MM-DD
RETURN_DATE = "2026-11-30"  # YYYY-MM-DD

ADULTS = 2

GOAL_PRICE_PER_ADULT = 800.0

CSV_PATH = str(REPO_ROOT / "historico_precos.csv")
SUMMARY_PATH = str(REPO_ROOT / "resumo.md")

CSV_HEADER = [
    "data_consulta",
    "horario_consulta",
    "preco_por_adulto",
    "preco_total_2_adultos",
    "companhia_voo",
    "fonte",
    "link",
    "observacoes",
]

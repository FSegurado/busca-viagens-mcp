"""Utilitários de debug compartilhados pelos scrapers.

Como o desenvolvimento deste projeto acontece num ambiente sem acesso à
internet (só o runner do GitHub Actions consegue abrir os sites de
verdade), o canal principal de depuração são os LOGS do job (lidos via API
do GitHub), não os artifacts de screenshot/HTML -- o storage de artifacts
não é alcançável de fora do Actions. Por isso `diagnostico()` imprime no
stdout um resumo dos elementos interativos da página (inputs, botões,
elementos com role) sempre que algo falha.
"""
from pathlib import Path


def dump(page, debug_dir: Path, tag: str, log) -> None:
    debug_dir.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(debug_dir / f"{tag}.png"), full_page=True)
        (debug_dir / f"{tag}.html").write_text(page.content(), encoding="utf-8")
        log(f"debug salvo em {debug_dir}/{tag}.(png|html) [artifact do job]")
    except Exception as exc:
        log(f"falha ao salvar debug: {exc}")


def diagnostico(page, log, max_items: int = 50) -> None:
    """Imprime nos logs os elementos interativos visíveis da página atual."""
    try:
        log(f"URL atual: {page.url}")
        log(f"Título da página: {page.title()!r}")
        itens = page.evaluate(
            """
            (max) => {
                const out = [];
                const seletor = 'input, button, [role=combobox], [role=textbox], [role=button], [role=option]';
                document.querySelectorAll(seletor).forEach(el => {
                    if (out.length >= max) return;
                    const rect = el.getBoundingClientRect();
                    if (rect.width === 0 && rect.height === 0) return;
                    const label = el.getAttribute('aria-label')
                        || el.getAttribute('placeholder')
                        || (el.innerText || '').trim();
                    if (!label) return;
                    const role = el.getAttribute('role') || el.tagName.toLowerCase();
                    out.push(`${role}: "${label.slice(0, 90)}"`);
                });
                return out;
            }
            """,
            max_items,
        )
        if itens:
            log(f"elementos interativos visíveis ({len(itens)}):")
            for item in itens:
                log(f"   {item}")
        else:
            log("nenhum elemento interativo visível encontrado (página pode estar vazia/bloqueada)")

        corpo = page.inner_text("body")[:300].replace("\n", " ")
        log(f"início do texto da página: {corpo!r}")
    except Exception as exc:
        log(f"falha ao coletar diagnóstico: {exc}")

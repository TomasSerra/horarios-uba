from __future__ import annotations

import argparse
import sys
import time
from collections import Counter

from .config import CATEDRA_URL, DELAY_SECONDS
from .db import (
    contar_vigentes,
    dar_de_baja_no_vistas,
    get_conn,
    listar_a_dar_de_baja,
    save_detalle,
)
from .discover import IndexEntry, discover_catedras
from .http import fetch
from .parse import parse_catedra_page
from .vigencia import evaluar_sweep


def scrape_catedra(catedra_id: int) -> None:
    html = fetch(CATEDRA_URL, params={"catedra": catedra_id})
    detalle = parse_catedra_page(html)
    if detalle is None:
        print(f"  catedra={catedra_id}: sin datos parseables (omitida)")
        return
    # Modo --catedra: no pasamos por discovery, así que no sabemos la carrera.
    # save_detalle deja la columna sin tocar si la fila ya existe.
    with get_conn() as conn:
        save_detalle(conn, detalle)
    counts = Counter(c.tipo for c in detalle.cursos)
    print(
        f"  catedra={catedra_id}: {detalle.materia_nombre} "
        f"(T:{counts.get('teorico', 0)} S:{counts.get('seminario', 0)} "
        f"C:{counts.get('comision', 0)})"
    )


def scrape_many(entries: list[IndexEntry], delay: float) -> int:
    """Scrapea las cátedras del índice. Devuelve cuántas fallaron."""
    total = len(entries)
    failed: list[tuple[int, str]] = []
    for i, entry in enumerate(entries, start=1):
        prefix = f"[{i}/{total}]"
        try:
            html = fetch(CATEDRA_URL, params={"catedra": entry.catedra_id})
            detalle = parse_catedra_page(html)
            if detalle is None:
                print(f"{prefix} catedra={entry.catedra_id}: sin datos (omitida)")
                continue
            with get_conn() as conn:
                save_detalle(conn, detalle, carrera=entry.carrera_slug)
            counts = Counter(c.tipo for c in detalle.cursos)
            print(
                f"{prefix} catedra={entry.catedra_id}: {detalle.materia_nombre} "
                f"(T:{counts.get('teorico', 0)} S:{counts.get('seminario', 0)} "
                f"C:{counts.get('comision', 0)})"
            )
        except Exception as exc:
            print(f"{prefix} catedra={entry.catedra_id}: ERROR {exc!r}")
            failed.append((entry.catedra_id, repr(exc)))
        if i < total:
            time.sleep(delay)
    print()
    print(f"Resumen: {total - len(failed)}/{total} OK, {len(failed)} fallidas")
    for cid, err in failed:
        print(f"  catedra={cid}: {err}")
    return len(failed)


def dar_de_baja_ausentes(
    descubiertas: list[int], forzar: bool, dry_run: bool
) -> bool:
    """Marca no vigentes las cátedras que ya no están en el índice. True si salió OK.

    El set de referencia es el del **índice**, no el de las cátedras guardadas con
    éxito: que la página de detalle de una cátedra falle no significa que haya
    dejado de dictarse.
    """
    with get_conn() as conn:
        vigentes = contar_vigentes(conn)
        decision = evaluar_sweep(len(descubiertas), vigentes, forzar=forzar)

        if not decision.barrer:
            print(f"Baja de cátedras OMITIDA: {decision.motivo}")
            return False

        if dry_run:
            pendientes = listar_a_dar_de_baja(conn, descubiertas)
            print(f"[dry-run] {decision.motivo}")
            print(f"[dry-run] se darían de baja {len(pendientes)} cátedras:")
            for cid, materia in pendientes:
                print(f"[dry-run]   catedra={cid}: {materia}")
            return True

        bajas = dar_de_baja_no_vistas(conn, descubiertas)
        print(f"Baja de cátedras: {decision.motivo}")
        print(f"  {bajas} marcadas como no vigentes (no se borró ninguna fila)")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scraper de horarios de Psicología (UBA)"
    )
    parser.add_argument(
        "--catedra",
        type=int,
        help="Scrapea solo esta cátedra (no consulta el índice)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Procesa solo las primeras N cátedras del índice",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DELAY_SECONDS,
        help=f"Segundos entre requests (default: {DELAY_SECONDS})",
    )
    parser.add_argument(
        "--force-sweep",
        action="store_true",
        help=(
            "Da de baja las cátedras ausentes del índice aunque este traiga menos "
            "de las esperadas. Usar cuando el recorte de la oferta es real."
        ),
    )
    parser.add_argument(
        "--dry-run-sweep",
        action="store_true",
        help=(
            "Sólo consulta el índice y lista qué cátedras se darían de baja. "
            "No scrapea ni escribe nada: es seguro correrlo contra producción."
        ),
    )
    args = parser.parse_args(argv)

    if args.catedra is not None:
        print(f"Scrapeando cátedra {args.catedra}...")
        scrape_catedra(args.catedra)
        return 0

    print("Descubriendo cátedras desde el índice...")
    try:
        entries = discover_catedras()
    except Exception as exc:
        print(f"ERROR al descubrir cátedras: {exc!r}")
        print("No se tocó la DB: la oferta actual queda como está.")
        return 1

    print(f"  {len(entries)} cátedras encontradas")
    if not entries:
        # 200 pero índice vacío o HTML cambiado. Antes era un no-op silencioso
        # que dejaba el Action en verde.
        print("ERROR: el índice vino vacío. No se tocó la DB.")
        return 1

    descubiertas = [e.catedra_id for e in entries]
    print()

    if args.dry_run_sweep:
        # Preview read-only: se saltea el scrapeo para que sea rápido y para no
        # escribir nada. Sirve para eyeballear el impacto antes de la corrida real.
        ok = dar_de_baja_ausentes(descubiertas, forzar=args.force_sweep, dry_run=True)
        return 0 if ok else 1

    if args.limit is not None:
        entries = entries[: args.limit]
        print(f"  --limit aplicado: {len(entries)} a procesar")

    scrape_many(entries, args.delay)
    print()

    if args.limit is not None:
        # Con --limit se procesó un subconjunto: dar de baja acá sería incorrecto.
        print("Baja de cátedras OMITIDA: corrida con --limit")
        return 0

    ok = dar_de_baja_ausentes(descubiertas, forzar=args.force_sweep, dry_run=False)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

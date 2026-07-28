from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import time

from bs4 import BeautifulSoup, Tag

TIPO_BY_HEADER = {
    "Teóricos": "teorico",
    "Seminarios": "seminario",
    "Comisiones": "comision",
}

HEADER_RE = re.compile(
    r"(?P<cuatrimestre>\d{4}/\d)\s*\*\s*"
    r"Listado horarios de cátedra\s+(?P<catedra_id>\d+)\s*-\s*"
    r"(?P<numero>[^-*]*?)\s*-\s*"
    r"(?P<titular>.*?)\s*\*\s*"
    r"Materia\s*\(\s*(?P<materia_codigo>\d+)\s*-\s*(?P<materia_nombre>.*?)\s*\)"
)

AULA_RE = re.compile(r"^([A-Z]+)\s*-")
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


@dataclass
class Curso:
    tipo: str
    codigo: str
    dia: str | None
    hora_inicio: time | None
    hora_fin: time | None
    profesor: str | None
    vacantes: int | None
    obligatorio: str | None
    aula: str | None
    sede: str | None
    observaciones: str | None
    # Encuentros adicionales de este mismo curso: filas que la fuente publica sin
    # código, debajo de la principal. No se elige entre ellos, van todos juntos.
    partes: list["Curso"] = field(default_factory=list)


@dataclass
class CatedraDetalle:
    catedra_id: int
    cuatrimestre: str | None
    numero: str | None
    titular: str | None
    materia_codigo: int
    materia_nombre: str
    cursos: list[Curso]


def parse_catedra_page(html: str) -> CatedraDetalle | None:
    soup = BeautifulSoup(html, "lxml")

    header_text = _extract_header_text(soup)
    if header_text is None:
        return None
    match = HEADER_RE.search(header_text)
    if match is None:
        return None

    catedra_id = int(match.group("catedra_id"))
    materia_codigo = int(match.group("materia_codigo"))
    materia_nombre = _clean(match.group("materia_nombre"))
    numero = _clean(match.group("numero")) or None
    titular = _clean(match.group("titular")) or None
    cuatrimestre = match.group("cuatrimestre")

    cursos: list[Curso] = []
    for table in soup.find_all("table", class_="table_tabs"):
        first_th = table.find("th")
        if first_th is None:
            continue
        header_label = first_th.get_text(strip=True).replace("\xa0", "").strip()
        tipo = TIPO_BY_HEADER.get(header_label)
        if tipo is None:
            continue
        cursos.extend(_parse_rows(table, tipo))

    return CatedraDetalle(
        catedra_id=catedra_id,
        cuatrimestre=cuatrimestre,
        numero=numero,
        titular=titular,
        materia_codigo=materia_codigo,
        materia_nombre=materia_nombre,
        cursos=cursos,
    )


def _extract_header_text(soup: BeautifulSoup) -> str | None:
    cell = soup.find("td", class_="option1")
    if cell is None:
        return None
    return _clean(cell.get_text(" ", strip=True))


def _parse_rows(table: Tag, tipo: str) -> list[Curso]:
    """Devuelve los cursos de la tabla. Una fila sin código no es un curso nuevo
    sino otro encuentro del anterior: la fuente parte así las comisiones que se
    cursan más de una vez por semana (ver `Curso.partes`)."""
    rows = table.find_all("tr")
    if not rows:
        return []
    out: list[Curso] = []
    for row in rows[1:]:  # skip header
        cells = row.find_all("td")
        if len(cells) < 10:
            continue
        codigo = _cell_text(cells[0])
        if not codigo and not out:
            # Continuación sin principal: no hay a qué colgarla.
            continue
        aula = _cell_text(cells[8]) or None
        curso = Curso(
            tipo=tipo,
            codigo=codigo or out[-1].codigo,
            dia=_cell_text(cells[1]) or None,
            hora_inicio=_parse_time(_cell_text(cells[2])),
            hora_fin=_parse_time(_cell_text(cells[3])),
            profesor=_cell_text(cells[5]) or None,
            vacantes=_parse_int(_cell_text(cells[6])),
            obligatorio=_cell_text(cells[7]) or None,
            aula=aula,
            sede=_sede_from_aula(aula),
            observaciones=_normalize_obs(_cell_text(cells[9])),
        )
        if codigo:
            out.append(curso)
        else:
            out[-1].partes.append(curso)
    return out


def _cell_text(cell: Tag) -> str:
    return _clean(cell.get_text(" ", strip=True).replace("\xa0", " "))


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _parse_time(value: str) -> time | None:
    if not value:
        return None
    match = TIME_RE.match(value)
    if match is None:
        return None
    hh, mm = int(match.group(1)), int(match.group(2))
    if not (0 <= hh < 24 and 0 <= mm < 60):
        return None
    return time(hh, mm)


def _parse_int(value: str) -> int | None:
    if not value or not value.lstrip("-").isdigit():
        return None
    return int(value)


def _sede_from_aula(aula: str | None) -> str | None:
    if not aula:
        return None
    match = AULA_RE.match(aula)
    return match.group(1) if match else None


def _normalize_obs(value: str) -> str | None:
    if not value or value.strip() in {".", ""}:
        return None
    return value

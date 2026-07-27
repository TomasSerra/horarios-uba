"""Armador de planes de cursada.

Dada una selección de materias y restricciones del usuario, genera todas las
combinaciones válidas (sin solapamiento horario) — una opción por materia,
donde cada opción es comisión + sus cursos obligados (teóricos/seminarios).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import time
from itertools import combinations, product as iproduct
from typing import Callable, Iterable, Iterator

from pydantic import BaseModel, Field, model_validator

from .models import CursoSummary


DIAS_VALIDOS = {"lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"}


class FranjaExcluida(BaseModel):
    dias: list[str] = Field(..., min_length=1, description="Uno o más días: lunes/.../sabado")
    hora_inicio: time
    hora_fin: time


class MateriaSeleccionada(BaseModel):
    codigo: int
    catedra_id: int | None = Field(
        None, description="Si se setea, restringe a esta cátedra; si no, permite todas"
    )
    profesores: list[str] | None = Field(
        default=None,
        description=(
            "Profesores permitidos para las comisiones de esta materia. "
            "None / ausente = todos. Lista vacía = ninguno (esa materia no "
            "tendrá opciones). Solo aplica al curso comisión, no a "
            "teóricos/seminarios."
        ),
    )
    sede: str | None = Field(
        default=None,
        description=(
            "Sede específica para esta materia. Si se setea, hace override "
            "de sedes_permitidas general. None = se aplica el filtro general."
        ),
    )


class PlanRequest(BaseModel):
    materias: list[MateriaSeleccionada] = Field(..., min_length=1, max_length=10)
    dias_excluidos: list[str] = Field(
        default_factory=list,
        description="Días enteros en los que no se quiere cursar",
    )
    franjas_excluidas: list[FranjaExcluida] = Field(
        default_factory=list,
        description="Franjas horarias (días + rango) no disponibles",
    )
    sedes_permitidas: list[str] = Field(
        default_factory=list,
        description="Sedes permitidas (HY/IN/SI/AV/EC). Vacío = todas.",
    )
    max_bache_horas: float | None = Field(
        default=None,
        ge=0,
        description=(
            "Bache máximo permitido entre clases consecutivas del mismo día, "
            "en horas. None = sin límite."
        ),
    )
    min_dias_semana: int | None = Field(
        default=None,
        ge=1,
        le=7,
        description=(
            "Mínimo de días distintos en los que se reparten las clases del plan. "
            "None = sin mínimo."
        ),
    )
    max_dias_semana: int | None = Field(
        default=None,
        ge=1,
        le=7,
        description=(
            "Máximo de días distintos en los que se reparten las clases del plan. "
            "None = sin máximo."
        ),
    )
    min_horas_dia: float | None = Field(
        default=None,
        ge=0,
        description=(
            "Mínimo de horas por día (span: de la primera a la última clase de "
            "cada día con clases). None = sin mínimo."
        ),
    )
    max_horas_dia: float | None = Field(
        default=None,
        ge=0,
        description=(
            "Máximo de horas por día (span: de la primera a la última clase de "
            "cada día con clases). None = sin máximo."
        ),
    )
    max_planes: int = Field(20, ge=1, le=100)
    solo_con_cupos: bool = Field(
        default=False,
        description=(
            "Si True, descarta opciones cuya comisión no tenga cupos disponibles "
            "(vacantes NULL o <= 0). Teóricos/seminarios no se miran: comparten "
            "el cupo de la comisión vía comision_obliga."
        ),
    )

    @model_validator(mode="after")
    def _validar_rangos(self) -> "PlanRequest":
        if (
            self.min_dias_semana is not None
            and self.max_dias_semana is not None
            and self.min_dias_semana > self.max_dias_semana
        ):
            raise ValueError("min_dias_semana no puede ser mayor que max_dias_semana")
        if (
            self.min_horas_dia is not None
            and self.max_horas_dia is not None
            and self.min_horas_dia > self.max_horas_dia
        ):
            raise ValueError("min_horas_dia no puede ser mayor que max_horas_dia")
        return self


class CursoEnPlan(CursoSummary):
    catedra_id: int
    profesor: str | None = None
    sede: str | None = None
    vacantes: int | None = None


class OpcionMateria(BaseModel):
    materia_codigo: int
    materia_nombre: str
    catedra_id: int
    catedra_numero: str | None = None
    catedra_titular: str | None = None
    cursos: list[CursoEnPlan]  # comisión + obligaciones


class Plan(BaseModel):
    opciones: list[OpcionMateria]


class PlanResponse(BaseModel):
    planes: list[Plan]
    total_generados: int
    materias_sin_opciones: list[int] = Field(
        default_factory=list,
        description="Códigos de materia donde ninguna opción cumple las restricciones",
    )


def _curso_cumple_restricciones(
    curso: CursoEnPlan,
    dias_excluidos: set[str],
    franjas: list[FranjaExcluida],
    sedes_permitidas: set[str],
) -> bool:
    if sedes_permitidas and curso.sede and curso.sede not in sedes_permitidas:
        return False
    if curso.dia and curso.dia in dias_excluidos:
        return False
    if curso.dia and curso.hora_inicio and curso.hora_fin:
        for f in franjas:
            if curso.dia in f.dias and curso.hora_inicio < f.hora_fin and f.hora_inicio < curso.hora_fin:
                return False
    return True


def _time_to_hours(t: time) -> float:
    return t.hour + t.minute / 60 + t.second / 3600


def _plan_respeta_bache(
    cursos: Iterable[CursoEnPlan], max_bache_horas: float
) -> bool:
    """True si en ningún día del plan hay un hueco entre clases consecutivas
    que supere max_bache_horas."""
    by_day: dict[str, list[CursoEnPlan]] = defaultdict(list)
    for c in cursos:
        if c.dia and c.hora_inicio and c.hora_fin:
            by_day[c.dia].append(c)
    for day_cursos in by_day.values():
        if len(day_cursos) <= 1:
            continue
        day_cursos.sort(key=lambda c: c.hora_inicio)
        for a, b in zip(day_cursos, day_cursos[1:]):
            gap = _time_to_hours(b.hora_inicio) - _time_to_hours(a.hora_fin)
            if gap > max_bache_horas:
                return False
    return True


def _plan_respeta_dias_horas(
    cursos: Iterable[CursoEnPlan],
    min_dias: int | None,
    max_dias: int | None,
    min_horas: float | None,
    max_horas: float | None,
) -> bool:
    """True si el plan reparte sus clases en un número de días distintos dentro
    de [min_dias, max_dias] y cada día con clases tiene un span (de la primera a
    la última clase, huecos incluidos) dentro de [min_horas, max_horas]."""
    by_day: dict[str, list[CursoEnPlan]] = defaultdict(list)
    for c in cursos:
        if c.dia and c.hora_inicio and c.hora_fin:
            by_day[c.dia].append(c)
    n_dias = len(by_day)
    if min_dias is not None and n_dias < min_dias:
        return False
    if max_dias is not None and n_dias > max_dias:
        return False
    if min_horas is not None or max_horas is not None:
        for day_cursos in by_day.values():
            span = max(_time_to_hours(c.hora_fin) for c in day_cursos) - min(
                _time_to_hours(c.hora_inicio) for c in day_cursos
            )
            if min_horas is not None and span < min_horas:
                return False
            if max_horas is not None and span > max_horas:
                return False
    return True


def _opcion_key(op: OpcionMateria) -> int:
    # La comisión siempre es el primer curso (ver _fetch_opciones_por_materia).
    return op.cursos[0].id


def _differs_in(p1: Plan, p2: Plan, idx: int) -> bool:
    return _opcion_key(p1.opciones[idx]) != _opcion_key(p2.opciones[idx])


def _differs_only_in(p1: Plan, p2: Plan, idx: int) -> bool:
    for i, (a, b) in enumerate(zip(p1.opciones, p2.opciones)):
        same = _opcion_key(a) == _opcion_key(b)
        if i == idx and same:
            return False
        if i != idx and not same:
            return False
    return True


def _reorder_round_robin(planes: list[Plan], num_materias: int) -> list[Plan]:
    """Reordena los planes para que la materia que cambia entre planes
    consecutivos rote (plan 1→2 cambia materia 0, 2→3 cambia materia 1, ...).
    Si no hay candidato que cambie sólo la materia objetivo, cae a uno que
    cambie esa materia (entre otras) y, en última instancia, a cualquiera."""
    if len(planes) <= 1 or num_materias <= 1:
        return planes
    pool = list(planes)
    ordered = [pool.pop(0)]
    while pool:
        target = (len(ordered) - 1) % num_materias
        prev = ordered[-1]
        idx = next(
            (i for i, p in enumerate(pool) if _differs_only_in(prev, p, target)),
            None,
        )
        if idx is None:
            idx = next(
                (i for i, p in enumerate(pool) if _differs_in(prev, p, target)),
                None,
            )
        if idx is None:
            idx = 0
        ordered.append(pool.pop(idx))
    return ordered


def _enumerar_combos(
    opciones_validas: list[list[OpcionMateria]],
    max_bache_horas: float | None = None,
    min_dias_semana: int | None = None,
    max_dias_semana: int | None = None,
    min_horas_dia: float | None = None,
    max_horas_dia: float | None = None,
    target_pool: int | None = None,
    on_attempt: Callable[[], None] | None = None,
) -> Iterator[tuple[OpcionMateria, ...]]:
    """Enumera combos en orden de distancia de Hamming creciente desde el
    origen (todos los índices = 0). Para cada distancia d, recorre los C(n, d)
    subconjuntos de materias a variar × producto cartesiano de valores
    no-cero para esas materias. Filtra solapamiento y bache.

    La iteración por distancia es clave: garantiza que en los primeros combos
    yieldeados haya variación en TODAS las materias (no solo en las últimas
    como pasaría con DFS lex), lo que permite que _reorder_round_robin
    alterne la materia cambiante entre planes consecutivos.

    Memoria O(num_materias) — sin set visited ni queue. Corta apenas
    yieldeados target_pool combos válidos, y tiene un cap absoluto en combos
    examinados como red de seguridad.
    """
    n = len(opciones_validas)
    if n == 0:
        return
    sizes = [len(o) for o in opciones_validas]
    # max distancia útil = materias con más de una opción (las de tamaño 1
    # nunca contribuyen una posición variable).
    max_dist = sum(1 for s in sizes if s > 1)
    yielded = 0
    examined = 0
    MAX_EXAMINED = 200_000

    for dist in range(max_dist + 1):
        for positions in combinations(range(n), dist):
            ranges = [range(1, sizes[p]) for p in positions]
            for vals in iproduct(*ranges):
                examined += 1
                if examined > MAX_EXAMINED:
                    return
                if on_attempt is not None:
                    on_attempt()
                indices = [0] * n
                for p, v in zip(positions, vals):
                    indices[p] = v
                combo = tuple(opciones_validas[i][indices[i]] for i in range(n))
                cursos = [c for op in combo for c in op.cursos]
                if _hay_solapamiento(cursos):
                    continue
                if max_bache_horas is not None and not _plan_respeta_bache(
                    cursos, max_bache_horas
                ):
                    continue
                if (
                    min_dias_semana is not None
                    or max_dias_semana is not None
                    or min_horas_dia is not None
                    or max_horas_dia is not None
                ) and not _plan_respeta_dias_horas(
                    cursos,
                    min_dias_semana,
                    max_dias_semana,
                    min_horas_dia,
                    max_horas_dia,
                ):
                    continue
                yield combo
                yielded += 1
                if target_pool is not None and yielded >= target_pool:
                    return


def _hay_solapamiento(cursos: Iterable[CursoEnPlan]) -> bool:
    by_day: dict[str, list[CursoEnPlan]] = defaultdict(list)
    for c in cursos:
        if c.dia and c.hora_inicio and c.hora_fin:
            by_day[c.dia].append(c)
    for day_cursos in by_day.values():
        day_cursos.sort(key=lambda c: c.hora_inicio)
        for a, b in zip(day_cursos, day_cursos[1:]):
            if a.hora_fin > b.hora_inicio:
                return True
    return False


def _fetch_opciones_por_materia(conn, materia_codigos: list[int]) -> dict[int, list[OpcionMateria]]:
    """Para cada materia, devuelve todas sus opciones de cursada
    (una por comisión, con sus obligaciones expandidas).

    Sólo cátedras vigentes: los cursos de una cátedra que dejó de dictarse siguen
    en la DB (los necesitan las reseñas) pero no deben generar planes. Sin este
    filtro se arman planes con los horarios del cuatrimestre anterior."""
    rows = conn.execute(
        """
        SELECT m.codigo AS materia_codigo, m.nombre AS materia_nombre,
               ca.id AS catedra_id, ca.numero AS catedra_numero,
               ca.titular AS catedra_titular,
               com.id AS comision_id, com.codigo AS comision_codigo,
               com.dia, com.hora_inicio, com.hora_fin,
               com.profesor, com.aula, com.sede, com.vacantes
          FROM materias m
          JOIN catedras ca ON ca.materia_codigo = m.codigo AND ca.vigente
          JOIN cursos com ON com.catedra_id = ca.id AND com.tipo = 'comision'
         WHERE m.codigo = ANY(%s)
         ORDER BY m.codigo, ca.id, LENGTH(com.codigo), com.codigo
        """,
        (materia_codigos,),
    ).fetchall()

    if not rows:
        return {cod: [] for cod in materia_codigos}

    comision_ids = [r["comision_id"] for r in rows]
    obliga_rows = conn.execute(
        """
        SELECT co.comision_id,
               t.id, t.tipo::text AS tipo, t.codigo, t.dia,
               t.hora_inicio, t.hora_fin, t.aula, t.profesor, t.sede,
               t.catedra_id, t.vacantes
          FROM comision_obliga co
          JOIN cursos t ON t.id = co.obliga_a_id
         WHERE co.comision_id = ANY(%s)
         ORDER BY t.tipo, t.codigo
        """,
        (comision_ids,),
    ).fetchall()

    obliga_map: dict[int, list[CursoEnPlan]] = defaultdict(list)
    for r in obliga_rows:
        cid = r.pop("comision_id")
        obliga_map[cid].append(CursoEnPlan(**r))

    opciones_por_materia: dict[int, list[OpcionMateria]] = {cod: [] for cod in materia_codigos}
    for r in rows:
        comision = CursoEnPlan(
            id=r["comision_id"],
            tipo="comision",
            codigo=r["comision_codigo"],
            dia=r["dia"],
            hora_inicio=r["hora_inicio"],
            hora_fin=r["hora_fin"],
            aula=r["aula"],
            profesor=r["profesor"],
            sede=r["sede"],
            catedra_id=r["catedra_id"],
            vacantes=r["vacantes"],
        )
        cursos = [comision, *obliga_map.get(r["comision_id"], [])]
        opciones_por_materia[r["materia_codigo"]].append(
            OpcionMateria(
                materia_codigo=r["materia_codigo"],
                materia_nombre=r["materia_nombre"],
                catedra_id=r["catedra_id"],
                catedra_numero=r["catedra_numero"],
                catedra_titular=r["catedra_titular"],
                cursos=cursos,
            )
        )
    return opciones_por_materia


def armar_planes(conn, req: PlanRequest) -> PlanResponse:
    dias_excluidos = {d.lower() for d in req.dias_excluidos}
    sedes_permitidas = set(req.sedes_permitidas)
    materia_codigos = [m.codigo for m in req.materias]
    selecciones_por_codigo: dict[int, MateriaSeleccionada] = {m.codigo: m for m in req.materias}

    opciones_por_materia = _fetch_opciones_por_materia(conn, materia_codigos)

    opciones_validas: list[list[OpcionMateria]] = []
    materias_sin_opciones: list[int] = []
    for cod in materia_codigos:
        seleccion = selecciones_por_codigo[cod]
        opciones = opciones_por_materia.get(cod, [])

        # Filtrar por cátedra elegida (si la hay).
        if seleccion.catedra_id is not None:
            opciones = [op for op in opciones if op.catedra_id == seleccion.catedra_id]

        # Filtrar por profesores permitidos. Semántica:
        #   None  -> sin filtro (todos los profesores permitidos)
        #   []    -> ninguno permitido -> 0 opciones
        #   [...]  -> solo comisiones cuyo profesor esté en la lista
        # Solo aplica al curso de tipo comisión: teóricos/seminarios vienen
        # "atados" a la comisión.
        if seleccion.profesores is None:
            pass
        elif not seleccion.profesores:
            opciones = []
        else:
            profesores_permitidos = set(seleccion.profesores)
            opciones = [
                op for op in opciones
                if any(
                    c.tipo == "comision" and c.profesor in profesores_permitidos
                    for c in op.cursos
                )
            ]

        # Sede específica por materia hace override del filtro general.
        sedes_efectivas = (
            {seleccion.sede} if seleccion.sede else sedes_permitidas
        )

        validas = [
            op for op in opciones
            if all(
                _curso_cumple_restricciones(c, dias_excluidos, req.franjas_excluidas, sedes_efectivas)
                for c in op.cursos
            )
        ]

        # Solo la comisión (siempre cursos[0]) tiene `vacantes`: teóricos y
        # seminarios comparten el cupo vía comision_obliga y vienen con NULL.
        if req.solo_con_cupos:
            validas = [
                op for op in validas
                if op.cursos[0].vacantes is not None and op.cursos[0].vacantes > 0
            ]

        if not validas:
            materias_sin_opciones.append(cod)
        else:
            opciones_validas.append(validas)

    if materias_sin_opciones:
        return PlanResponse(planes=[], total_generados=0, materias_sin_opciones=materias_sin_opciones)

    # Generamos un pool más grande que max_planes para que el reorden
    # round-robin tenga material para diversificar (si solo tomáramos los
    # primeros max_planes de itertools.product, todos diferirían en la última
    # materia y el reorden no podría rotar).
    POOL_MULTIPLIER = 10
    POOL_HARD_CAP = 1000
    pool_target = min(req.max_planes * POOL_MULTIPLIER, POOL_HARD_CAP)

    planes: list[Plan] = []
    total = 0

    def _bump() -> None:
        nonlocal total
        total += 1

    for combo in _enumerar_combos(
        opciones_validas,
        max_bache_horas=req.max_bache_horas,
        min_dias_semana=req.min_dias_semana,
        max_dias_semana=req.max_dias_semana,
        min_horas_dia=req.min_horas_dia,
        max_horas_dia=req.max_horas_dia,
        target_pool=pool_target,
        on_attempt=_bump,
    ):
        planes.append(Plan(opciones=list(combo)))
        if len(planes) >= pool_target:
            break

    planes = _reorder_round_robin(planes, num_materias=len(opciones_validas))[
        : req.max_planes
    ]

    return PlanResponse(
        planes=planes,
        total_generados=total,
        materias_sin_opciones=[],
    )

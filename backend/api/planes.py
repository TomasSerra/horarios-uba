"""Armador de planes de cursada.

Dada una selección de materias y restricciones del usuario, genera todas las
combinaciones válidas (sin solapamiento horario) — una opción por materia,
donde cada opción es comisión + los teóricos/seminarios que la acompañan.
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
    comision_codigo: str | None = Field(
        default=None,
        description=(
            "Código de la comisión a fijar. Requiere catedra_id: los códigos "
            "de comisión son únicos por cátedra, no globalmente."
        ),
    )
    teorico_libre: bool = Field(
        default=False,
        description=(
            "Si es True, la comisión puede ir con cualquier teórico de su "
            "cátedra en vez de sólo con el que obliga. False (default) = "
            "comportamiento atado de siempre."
        ),
    )
    seminario_libre: bool = Field(
        default=False,
        description="Idem teorico_libre, para los seminarios.",
    )

    @model_validator(mode="after")
    def _comision_requiere_catedra(self) -> "MateriaSeleccionada":
        if self.comision_codigo is not None and self.catedra_id is None:
            raise ValueError("comision_codigo requiere catedra_id")
        return self


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


def _opcion_key(op: OpcionMateria) -> tuple[int, ...]:
    # Todos los cursos, no sólo la comisión: con teorico_libre/seminario_libre dos
    # opciones distintas comparten comisión y sólo se diferencian en el teórico.
    return tuple(c.id for c in op.cursos)


# Firma de un plan: una clave de opción por materia. Se compara entre planes para
# decidir el orden.
PlanKey = tuple[tuple[int, ...], ...]


def _differs_only_in(k1: PlanKey, k2: PlanKey, idx: int) -> bool:
    for i, (a, b) in enumerate(zip(k1, k2)):
        same = a == b
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
    # Las claves se calculan una sola vez: el matching es O(n²) sobre un pool de
    # hasta 1000 planes, y recalcularlas en cada comparación domina el costo.
    pool = [(p, tuple(_opcion_key(op) for op in p.opciones)) for p in planes]
    ordered = [pool.pop(0)]
    while pool:
        target = (len(ordered) - 1) % num_materias
        prev = ordered[-1][1]
        idx = next(
            (i for i, (_, k) in enumerate(pool) if _differs_only_in(prev, k, target)),
            None,
        )
        if idx is None:
            idx = next(
                (i for i, (_, k) in enumerate(pool) if prev[target] != k[target]),
                None,
            )
        if idx is None:
            idx = 0
        ordered.append(pool.pop(idx))
    return [p for p, _ in ordered]


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


def _variantes_de_tipo(
    obligados: list[CursoEnPlan],
    catalogo: list[CursoEnPlan],
    libre: bool,
    requerido: bool,
) -> list[tuple[CursoEnPlan, ...]]:
    """Cursos de un tipo (teórico o seminario) que puede llevar una comisión.

    La primera variante es siempre la "natural" (la que arma el plan de hoy): el
    orden importa porque `_enumerar_combos` explora los índices bajos primero.

    `requerido` distingue los dos tipos cuando la comisión no obliga ninguno: al
    teórico hay que cursarlo igual (va cualquiera de la cátedra), mientras que un
    seminario que nadie obliga es optativo y no entra al plan.
    """
    if obligados:
        # Con tantos cursos en la cátedra como obligados hay una sola combinación
        # posible, que es la obligada.
        if not libre or len(catalogo) <= len(obligados):
            return [tuple(obligados)]
        ids = {c.id for c in obligados}
        return [
            tuple(obligados),
            *(
                combo
                for combo in combinations(catalogo, len(obligados))
                if {c.id for c in combo} != ids
            ),
        ]
    if not requerido or not catalogo:
        return [()]
    return [(c,) for c in catalogo]


def _fetch_opciones_por_materia(
    conn, materia_codigos: list[int], libres: dict[int, tuple[bool, bool]]
) -> dict[int, list[OpcionMateria]]:
    """Para cada materia, devuelve todas sus opciones de cursada
    (comisión + teóricos/seminarios que le corresponden, con sus partes expandidas).

    `libres` mapea materia -> (teorico_libre, seminario_libre): con el flag en
    True la comisión puede llevar cualquier curso de ese tipo de su cátedra en vez
    del que obliga. Ver `_variantes_de_tipo` para las cuatro situaciones.

    Sólo cátedras vigentes: los cursos de una cátedra que dejó de dictarse siguen
    en la DB (los necesitan las reseñas) pero no deben generar planes. Sin este
    filtro se arman planes con los horarios del cuatrimestre anterior.

    Sólo filas principales (`parte_de_id IS NULL`) como comisión: una parte no es
    una opción alternativa sino otro encuentro obligatorio de la misma comisión,
    y se suma abajo a los cursos de la opción."""
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
                         AND com.parte_de_id IS NULL
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

    # Todos los teóricos y seminarios de las cátedras en juego. Se trae siempre
    # (no sólo con los flags prendidos) porque una comisión que no obliga teórico
    # igual tiene que llevar uno.
    catalogo_rows = conn.execute(
        """
        SELECT t.id, t.tipo::text AS tipo, t.codigo, t.dia,
               t.hora_inicio, t.hora_fin, t.aula, t.profesor, t.sede,
               t.catedra_id, t.vacantes
          FROM cursos t
         WHERE t.catedra_id = ANY(%s)
           AND t.tipo IN ('teorico', 'seminario')
           AND t.parte_de_id IS NULL
         ORDER BY t.tipo, LENGTH(t.codigo), t.codigo
        """,
        (sorted({r["catedra_id"] for r in rows}),),
    ).fetchall()

    catalogo: dict[tuple[int, str], list[CursoEnPlan]] = defaultdict(list)
    for r in catalogo_rows:
        curso = CursoEnPlan(**r)
        catalogo[(curso.catedra_id, curso.tipo)].append(curso)

    # Encuentros extra de las comisiones y de los cursos que las acompañan. Van sí
    # o sí con el curso al que pertenecen: inscribirse en la comisión te inscribe
    # en todos.
    partes_rows = conn.execute(
        """
        SELECT p.parte_de_id,
               p.id, p.tipo::text AS tipo, p.codigo, p.dia,
               p.hora_inicio, p.hora_fin, p.aula, p.profesor, p.sede,
               p.catedra_id, p.vacantes
          FROM cursos p
         WHERE p.parte_de_id = ANY(%s)
         ORDER BY p.id
        """,
        (
            comision_ids
            + [r["id"] for r in obliga_rows]
            + [r["id"] for r in catalogo_rows],
        ),
    ).fetchall()

    partes_map: dict[int, list[CursoEnPlan]] = defaultdict(list)
    for r in partes_rows:
        partes_map[r.pop("parte_de_id")].append(CursoEnPlan(**r))

    def _con_partes(curso: CursoEnPlan) -> list[CursoEnPlan]:
        return [curso, *partes_map.get(curso.id, [])]

    # Se acumulan con (variante, orden de la comisión) para poder ordenar después.
    buckets: dict[int, list[tuple[int, int, OpcionMateria]]] = defaultdict(list)
    for orden, r in enumerate(rows):
        teorico_libre, seminario_libre = libres.get(r["materia_codigo"], (False, False))
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
        obligados = obliga_map.get(r["comision_id"], [])
        variantes_teorico = _variantes_de_tipo(
            [c for c in obligados if c.tipo == "teorico"],
            catalogo.get((r["catedra_id"], "teorico"), []),
            teorico_libre,
            requerido=True,
        )
        variantes_seminario = _variantes_de_tipo(
            [c for c in obligados if c.tipo == "seminario"],
            catalogo.get((r["catedra_id"], "seminario"), []),
            seminario_libre,
            requerido=False,
        )
        # La comisión principal queda primera: `solo_con_cupos` lee cursos[0] (es
        # la única fila que trae las vacantes).
        base = _con_partes(comision)
        for variante, (teoricos, seminarios) in enumerate(
            iproduct(variantes_teorico, variantes_seminario)
        ):
            cursos = [
                *base,
                *(c for extra in (*teoricos, *seminarios) for c in _con_partes(extra)),
            ]
            # model_construct saltea la validación: los valores ya salieron de
            # modelos validados y con los flags libres esto corre decenas de miles
            # de veces por request.
            buckets[r["materia_codigo"]].append(
                (
                    variante,
                    orden,
                    OpcionMateria.model_construct(
                        materia_codigo=r["materia_codigo"],
                        materia_nombre=r["materia_nombre"],
                        catedra_id=r["catedra_id"],
                        catedra_numero=r["catedra_numero"],
                        catedra_titular=r["catedra_titular"],
                        cursos=cursos,
                    ),
                )
            )

    # Primero todas las opciones naturales (una por comisión, en el orden de la
    # query) y recién después las recombinadas: `_enumerar_combos` explora los
    # índices bajos primero, así que sin esto los primeros planes serían todos la
    # misma comisión con distinto teórico.
    opciones_por_materia: dict[int, list[OpcionMateria]] = {cod: [] for cod in materia_codigos}
    for cod, items in buckets.items():
        items.sort(key=lambda t: (t[0], t[1]))
        opciones_por_materia[cod] = [op for _, _, op in items]
    return opciones_por_materia


def _materias_con_oferta_congelada(conn, codigos: list[int]) -> set[int]:
    rows = conn.execute(
        "SELECT codigo FROM materias WHERE oferta_congelada AND codigo = ANY(%s)",
        (codigos,),
    ).fetchall()
    return {r["codigo"] for r in rows}


def armar_planes(conn, req: PlanRequest) -> PlanResponse:
    dias_excluidos = {d.lower() for d in req.dias_excluidos}
    sedes_permitidas = set(req.sedes_permitidas)
    materia_codigos = [m.codigo for m in req.materias]
    selecciones_por_codigo: dict[int, MateriaSeleccionada] = {m.codigo: m for m in req.materias}

    # Los cupos de una materia con la oferta congelada son los del cuatrimestre
    # anterior: filtrarlos dejaría afuera a quien ya la está cursando.
    congeladas = (
        _materias_con_oferta_congelada(conn, materia_codigos)
        if req.solo_con_cupos
        else set()
    )

    opciones_por_materia = _fetch_opciones_por_materia(
        conn,
        materia_codigos,
        {m.codigo: (m.teorico_libre, m.seminario_libre) for m in req.materias},
    )

    opciones_validas: list[list[OpcionMateria]] = []
    materias_sin_opciones: list[int] = []
    for cod in materia_codigos:
        seleccion = selecciones_por_codigo[cod]
        opciones = opciones_por_materia.get(cod, [])

        # Filtrar por cátedra elegida (si la hay).
        if seleccion.catedra_id is not None:
            opciones = [op for op in opciones if op.catedra_id == seleccion.catedra_id]

        # Comisión exacta dentro de esa cátedra. `cursos[0]` es siempre la comisión;
        # el resto son sus teóricos/seminarios obligados.
        if seleccion.comision_codigo is not None:
            opciones = [
                op for op in opciones if op.cursos[0].codigo == seleccion.comision_codigo
            ]

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
        if req.solo_con_cupos and cod not in congeladas:
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

"""Tests de los circuit breakers del job horario de vacantes.

Lógica pura, sin fixtures ni DB: son la última línea antes de escribir en
producción, así que cada umbral se testea en su borde exacto (justo en el umbral
escribe, un paso abajo no).

Los números de los casos felices son los reales de la DB: 219 cátedras en el
índice, ~2.370 comisiones principales vigentes.
"""

from __future__ import annotations

import pytest

from scraper.vacantes_guardas import (
    MAX_CAMBIOS_RATIO,
    MAX_FALLOS_CONSECUTIVOS,
    MIN_CATEDRAS,
    MIN_MUESTRA_PARA_RATIO,
    MetricasVacantes,
    evaluar_actualizacion,
    evaluar_fetch,
    verificar_rowcount,
)


def _fetch_ok(**overrides) -> MetricasVacantes:
    """Métricas de un fetch sano: 219/219 páginas, 2.370 comisiones con valor."""
    base = dict(
        paginas_totales=219,
        paginas_ok=219,
        claves_fuente=2370,
        con_valor=2370,
    )
    base.update(overrides)
    return MetricasVacantes(**base)


def _diff_ok(**overrides) -> MetricasVacantes:
    """Métricas de un diff sano: cobertura total y 80 cambios en la hora."""
    base = dict(
        claves_fuente=2370,
        claves_consideradas=2370,
        claves_db=2370,
        matched=2370,
        sin_match_fuente=0,
        cambios=80,
    )
    base.update(overrides)
    return MetricasVacantes(**base)


class TestEvaluarFetch:
    def test_caso_feliz(self):
        d = evaluar_fetch(_fetch_ok())
        assert d.escribir
        assert "219/219" in d.motivo

    def test_indice_vacio_no_se_destraba_ni_con_force(self):
        for forzar in (False, True):
            d = evaluar_fetch(_fetch_ok(paginas_totales=0), forzar=forzar)
            assert not d.escribir
            assert "vacío" in d.motivo

    def test_corte_por_fallos_consecutivos(self):
        m = _fetch_ok(
            corte_por_fallos=True, fallos_consecutivos=MAX_FALLOS_CONSECUTIVOS
        )
        d = evaluar_fetch(m)
        assert not d.escribir
        assert "consecutivos" in d.motivo

    def test_corte_por_fallos_no_se_destraba_ni_con_force(self):
        # Si la fuente está bloqueando, --force no puede ser la respuesta.
        m = _fetch_ok(corte_por_fallos=True, fallos_consecutivos=10)
        assert not evaluar_fetch(m, forzar=True).escribir

    @pytest.mark.parametrize(
        "totales,escribe",
        [(MIN_CATEDRAS, True), (MIN_CATEDRAS - 1, False)],
    )
    def test_piso_de_catedras_en_el_borde(self, totales, escribe):
        m = _fetch_ok(paginas_totales=totales, paginas_ok=totales)
        assert evaluar_fetch(m).escribir is escribe

    def test_piso_de_catedras_se_destraba_con_force(self):
        m = _fetch_ok(paginas_totales=10, paginas_ok=10)
        assert evaluar_fetch(m, forzar=True).escribir

    @pytest.mark.parametrize(
        "ok,escribe",
        # 85% de 219 = 186.15 → 187 escribe, 186 no.
        [(219, True), (187, True), (186, False), (0, False)],
    )
    def test_paginas_ok_en_el_borde(self, ok, escribe):
        assert evaluar_fetch(_fetch_ok(paginas_ok=ok)).escribir is escribe

    def test_waf_reporta_el_desglose(self):
        m = _fetch_ok(paginas_ok=0, paginas_sin_parse=219)
        d = evaluar_fetch(m)
        assert not d.escribir
        assert "sin_parse=219" in d.motivo

    def test_sin_claves_no_escribe(self):
        m = _fetch_ok(claves_fuente=0, con_valor=0)
        d = evaluar_fetch(m)
        assert not d.escribir
        assert "nada que escribir" in d.motivo

    @pytest.mark.parametrize(
        "fuera,escribe",
        # 1% de 2370 = 23.7 → 23 escribe, 24 no.
        [(0, True), (23, True), (24, False)],
    )
    def test_fuera_de_rango_en_el_borde(self, fuera, escribe):
        m = _fetch_ok(fuera_de_rango=fuera, con_valor=2370 - fuera)
        assert evaluar_fetch(m).escribir is escribe

    @pytest.mark.parametrize(
        "con_valor,escribe",
        # 50% de 2370 = 1185 → 1185 escribe, 1184 no.
        [(2370, True), (1185, True), (1184, False)],
    )
    def test_con_valor_en_el_borde(self, con_valor, escribe):
        m = _fetch_ok(con_valor=con_valor, sin_valor=2370 - con_valor)
        assert evaluar_fetch(m).escribir is escribe


class TestEvaluarActualizacion:
    def test_caso_feliz(self):
        d = evaluar_actualizacion(_diff_ok())
        assert d.escribir
        assert "80" in d.motivo and "2370" in d.motivo

    def test_select_vacio_no_se_destraba_ni_con_force(self):
        for forzar in (False, True):
            d = evaluar_actualizacion(_diff_ok(claves_db=0), forzar=forzar)
            assert not d.escribir
            assert "vigente" in d.motivo

    @pytest.mark.parametrize(
        "matched,escribe",
        # 70% de 2370 = 1659 → 1659 escribe, 1658 no.
        [(2370, True), (1659, True), (1658, False)],
    )
    def test_cobertura_en_el_borde(self, matched, escribe):
        m = _diff_ok(matched=matched, cambios=0)
        assert evaluar_actualizacion(m).escribir is escribe

    def test_cobertura_baja_se_destraba_con_force(self):
        m = _diff_ok(matched=100, cambios=0)
        assert evaluar_actualizacion(m, forzar=True).escribir

    @pytest.mark.parametrize(
        "sin_match,escribe",
        # 15% de 2370 = 355.5 → 355 escribe, 356 no.
        [(0, True), (355, True), (356, False)],
    )
    def test_sin_match_fuente_en_el_borde(self, sin_match, escribe):
        m = _diff_ok(sin_match_fuente=sin_match)
        assert evaluar_actualizacion(m).escribir is escribe

    @pytest.mark.parametrize(
        "cambios,escribe",
        # 60% de 2370 = 1422 → 1422 escribe, 1423 no.
        [(80, True), (1422, True), (1423, False), (2370, False)],
    )
    def test_cambios_masivos_en_el_borde(self, cambios, escribe):
        assert evaluar_actualizacion(_diff_ok(cambios=cambios)).escribir is escribe

    def test_cambios_masivos_es_el_breaker_que_caza_el_corrimiento(self):
        # Un corrimiento de columna que dio ints plausibles cambia TODO de golpe.
        d = evaluar_actualizacion(_diff_ok(cambios=2370))
        assert not d.escribir
        assert "otra columna" in d.motivo

    def test_cambios_masivos_se_destraba_con_force(self):
        assert evaluar_actualizacion(_diff_ok(cambios=2370), forzar=True).escribir

    def test_muestra_chica_no_dispara_los_ratios(self):
        # Con 10 comisiones, 10 cambios es el 100% pero no dice nada: es lo que
        # pasa en una corrida con --limit. Debajo del piso el ratio no aplica.
        m = _diff_ok(
            claves_consideradas=10, claves_db=10, matched=10, cambios=10,
            sin_match_fuente=5,
        )
        assert evaluar_actualizacion(m).escribir

    def test_apenas_arriba_del_piso_el_ratio_vuelve_a_aplicar(self):
        m = _diff_ok(
            claves_consideradas=MIN_MUESTRA_PARA_RATIO,
            claves_db=MIN_MUESTRA_PARA_RATIO,
            matched=MIN_MUESTRA_PARA_RATIO,
            cambios=MIN_MUESTRA_PARA_RATIO,
        )
        assert not evaluar_actualizacion(m).escribir

    def test_force_con_cero_matched_no_divide_por_cero(self):
        m = _diff_ok(matched=0, cambios=0)
        d = evaluar_actualizacion(m, forzar=True)
        assert d.escribir
        assert "nada que escribir" in d.motivo

    def test_denominador_de_sin_match_es_lo_considerado(self):
        # 356 sobre las 2370 de la fuente aborta; sobre 2370 consideradas también.
        # Pero si sólo se consideraron 400 claves (el resto salteadas por
        # cuatrimestre), 100 sin match ya es el 25% y tiene que abortar.
        m = _diff_ok(claves_consideradas=400, sin_match_fuente=100, matched=400,
                     claves_db=400)
        assert not evaluar_actualizacion(m).escribir


class TestVerificarRowcount:
    def test_exacto_no_es_warning(self):
        assert verificar_rowcount(42, 42) is None

    def test_de_menos_pero_cerca_es_warning_no_error(self):
        # 95 de 100: alguien escribió el mismo valor en el medio. Benigno.
        warning = verificar_rowcount(95, 100)
        assert warning is not None
        assert "concurrente" in warning

    def test_de_mas_raisea(self):
        # Sólo puede pasar si la clave dejó de ser única entre comisiones.
        with pytest.raises(RuntimeError, match="única"):
            verificar_rowcount(43, 42)

    def test_muy_de_menos_raisea(self):
        with pytest.raises(RuntimeError, match="scope"):
            verificar_rowcount(50, 100)

    def test_cero_filas_para_payload_no_vacio_raisea(self):
        with pytest.raises(RuntimeError):
            verificar_rowcount(0, 42)


def test_los_umbrales_son_los_documentados():
    # Si alguien los cambia, que sea a propósito y actualizando el plan.
    assert MIN_CATEDRAS == 150
    assert MAX_CAMBIOS_RATIO == 0.6
    assert MAX_FALLOS_CONSECUTIVOS == 10
    assert MIN_MUESTRA_PARA_RATIO == 50

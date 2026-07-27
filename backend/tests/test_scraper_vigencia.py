"""Guardas del sweep del scraper.

Es la única operación que saca oferta de circulación, así que acá está el riesgo
real de "un día la fuente falla y la app se queda sin materias". Lógica pura, sin
DB ni red.
"""

from __future__ import annotations

import pytest

from scraper.vigencia import evaluar_sweep


class TestIndiceVacio:
    """El caso del hueco entre cuatrimestres: la fuente deja de publicar datos."""

    def test_indice_vacio_no_barre(self):
        d = evaluar_sweep(descubiertas=0, vigentes_actuales=500)
        assert d.barrer is False
        assert "vacío" in d.motivo

    def test_indice_vacio_no_barre_ni_con_force(self):
        # Barrer con el índice vacío daría de baja el 100% de la oferta: no hay
        # ningún escenario en que eso sea lo que el operador quiso pedir.
        d = evaluar_sweep(descubiertas=0, vigentes_actuales=500, forzar=True)
        assert d.barrer is False

    def test_indice_vacio_con_db_vacia_tampoco_barre(self):
        d = evaluar_sweep(descubiertas=0, vigentes_actuales=0)
        assert d.barrer is False


class TestPrimeraCorrida:
    def test_sin_vigentes_en_db_barre(self):
        # DB recién sembrada: no hay nada que dar de baja, el sweep es un no-op.
        d = evaluar_sweep(descubiertas=500, vigentes_actuales=0)
        assert d.barrer is True


class TestRatio:
    def test_indice_completo_barre(self):
        d = evaluar_sweep(descubiertas=500, vigentes_actuales=500)
        assert d.barrer is True

    def test_indice_mas_grande_barre(self):
        # Cuatrimestre nuevo con más oferta que el anterior.
        d = evaluar_sweep(descubiertas=600, vigentes_actuales=500)
        assert d.barrer is True

    def test_justo_en_el_umbral_barre(self):
        d = evaluar_sweep(descubiertas=250, vigentes_actuales=500, min_ratio=0.5)
        assert d.barrer is True

    def test_apenas_debajo_del_umbral_no_barre(self):
        d = evaluar_sweep(descubiertas=249, vigentes_actuales=500, min_ratio=0.5)
        assert d.barrer is False
        assert "--force-sweep" in d.motivo

    def test_carga_parcial_de_la_fuente_no_barre(self):
        # Una sola de las 4 carreras cargada: no es que se discontinuaron 3/4 de
        # las cátedras, es que la fuente está a medio publicar.
        d = evaluar_sweep(descubiertas=120, vigentes_actuales=500)
        assert d.barrer is False

    def test_motivo_reporta_los_numeros(self):
        d = evaluar_sweep(descubiertas=100, vigentes_actuales=500)
        assert "100" in d.motivo and "500" in d.motivo

    @pytest.mark.parametrize("min_ratio", [0.2, 0.5, 0.8])
    def test_umbral_configurable(self, min_ratio):
        vigentes = 1000
        justo = int(vigentes * min_ratio)
        assert evaluar_sweep(justo, vigentes, min_ratio=min_ratio).barrer is True
        assert evaluar_sweep(justo - 1, vigentes, min_ratio=min_ratio).barrer is False


class TestForzar:
    def test_force_barre_debajo_del_umbral(self):
        d = evaluar_sweep(descubiertas=100, vigentes_actuales=500, forzar=True)
        assert d.barrer is True
        assert "--force-sweep" in d.motivo

    def test_force_es_irrelevante_cuando_ya_pasaba(self):
        sin = evaluar_sweep(descubiertas=500, vigentes_actuales=500)
        con = evaluar_sweep(descubiertas=500, vigentes_actuales=500, forzar=True)
        assert sin.barrer is con.barrer is True


class TestDarDeBajaNoVistas:
    """La lista vacía apagaría toda la oferta: tiene que abortar."""

    def test_lista_vacia_aborta(self):
        from scraper.db import dar_de_baja_no_vistas

        with pytest.raises(ValueError):
            dar_de_baja_no_vistas(conn=None, vistas=[])

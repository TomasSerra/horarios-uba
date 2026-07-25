"""Tests de reseñas de cátedras: upsert (una por usuario, sin gate Pro),
borrado con ownership, detalle (mi reseña / anónimo / distribución) y ranking
(mapeo, total por COUNT(*) OVER, sort y paginación)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api.auth import AuthUser
from api.reviews import (
    ReviewUpsert,
    delete_review,
    get_catedra_reviews,
    list_catedras,
    upsert_review,
)

NOW = datetime.now(timezone.utc)


# ----------------------------- ReviewUpsert (validación) ----------------------

class TestReviewUpsert:
    def test_rating_fuera_de_rango(self):
        with pytest.raises(ValidationError):
            ReviewUpsert(rating=6, profesor="Prof X", anio=2024)
        with pytest.raises(ValidationError):
            ReviewUpsert(rating=0, profesor="Prof X", anio=2024)

    def test_comment_demasiado_largo(self):
        with pytest.raises(ValidationError):
            ReviewUpsert(rating=3, comment="x" * 1001, profesor="Prof X", anio=2024)

    def test_comment_opcional(self):
        r = ReviewUpsert(rating=4, anio=2024)
        assert r.comment is None

    def test_profesor_opcional(self):
        # Se puede reseñar solo la cátedra, sin profesor.
        r = ReviewUpsert(rating=4, anio=2024)
        assert r.profesor is None
        assert r.profesor_rating is None

    def test_profesor_vacio_invalido(self):
        with pytest.raises(ValidationError):
            ReviewUpsert(rating=4, profesor="", profesor_rating=3, anio=2024)

    def test_profesor_y_rating_emparejados(self):
        # Profesor sin nota o nota sin profesor: inválido (o los dos o ninguno).
        with pytest.raises(ValidationError):
            ReviewUpsert(rating=4, profesor="Prof X", anio=2024)
        with pytest.raises(ValidationError):
            ReviewUpsert(rating=4, profesor_rating=5, anio=2024)
        # Ambos juntos: válido.
        r = ReviewUpsert(rating=4, profesor="Prof X", profesor_rating=5, anio=2024)
        assert r.profesor == "Prof X"
        assert r.profesor_rating == 5

    def test_profesor_rating_fuera_de_rango(self):
        with pytest.raises(ValidationError):
            ReviewUpsert(rating=4, profesor="Prof X", profesor_rating=6, anio=2024)

    def test_anio_obligatorio_y_acotado(self):
        with pytest.raises(ValidationError):
            ReviewUpsert(rating=4)
        with pytest.raises(ValidationError):
            ReviewUpsert(rating=4, anio=1999)
        # No se puede reseñar una cursada futura.
        with pytest.raises(ValidationError):
            ReviewUpsert(rating=4, anio=NOW.year + 1)


# ----------------------------- upsert_review ----------------------------------

class TestUpsertReview:
    def test_inserta_y_commit(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.reviews.pool", fake_pool)
        fake_conn.on("select 1 from catedras", rows=[{"?column?": 1}])
        fake_conn.on("from cursos", rows=[{"?column?": 1}])
        fake_conn.on(
            "insert into catedra_reviews",
            rows=[
                {
                    "id": 1,
                    "rating": 5,
                    "comment": "genial",
                    "profesor": "Prof X",
                    "profesor_rating": 4,
                    "anio": 2024,
                    "created_at": NOW,
                    "updated_at": NOW,
                }
            ],
        )
        resp = upsert_review(
            catedra_id=1,
            body=ReviewUpsert(
                rating=5, comment="genial", profesor="Prof X",
                profesor_rating=4, anio=2024,
            ),
            user=AuthUser(id="uid"),
        )
        assert resp.id == 1
        assert resp.rating == 5
        assert resp.profesor == "Prof X"
        assert resp.profesor_rating == 4
        assert resp.anio == 2024
        assert fake_conn.commits == 1

    def test_profesor_ajeno_a_catedra_da_400(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.reviews.pool", fake_pool)
        fake_conn.on("select 1 from catedras", rows=[{"?column?": 1}])
        fake_conn.on("from cursos", rows=[])  # el profe no dicta en esta cátedra
        with pytest.raises(HTTPException) as exc:
            upsert_review(
                catedra_id=1,
                body=ReviewUpsert(
                    rating=5, profesor="Ajeno", profesor_rating=3, anio=2024
                ),
                user=AuthUser(id="uid"),
            )
        assert exc.value.status_code == 400

    def test_catedra_inexistente_da_404(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.reviews.pool", fake_pool)
        fake_conn.on("select 1 from catedras", rows=[])
        with pytest.raises(HTTPException) as exc:
            upsert_review(
                catedra_id=999,
                body=ReviewUpsert(
                    rating=5, profesor="Prof X", profesor_rating=5, anio=2024
                ),
                user=AuthUser(id="uid"),
            )
        assert exc.value.status_code == 404

    def test_comment_en_blanco_se_normaliza_a_null(
        self, monkeypatch, fake_pool, fake_conn
    ):
        captured = {}

        def cap(sql, params):
            captured["params"] = params

        monkeypatch.setattr("api.reviews.pool", fake_pool)
        fake_conn.on("select 1 from catedras", rows=[{"?column?": 1}])
        fake_conn.on("from cursos", rows=[{"?column?": 1}])
        fake_conn.on(
            "insert into catedra_reviews",
            rows=[
                {
                    "id": 1,
                    "rating": 4,
                    "comment": None,
                    "profesor": "Prof X",
                    "profesor_rating": 4,
                    "anio": 2024,
                    "created_at": NOW,
                    "updated_at": NOW,
                }
            ],
            side_effect=cap,
        )
        upsert_review(
            catedra_id=1,
            body=ReviewUpsert(
                rating=4, comment="   ", profesor="Prof X",
                profesor_rating=4, anio=2024,
            ),
            user=AuthUser(id="uid"),
        )
        # params = (catedra_id, user.id, rating, comment, profesor, profesor_rating, anio)
        assert captured["params"][3] is None

    def test_upsert_manda_uid_y_rating(self, monkeypatch, fake_pool, fake_conn):
        captured = {}

        def cap(sql, params):
            captured["params"] = params

        monkeypatch.setattr("api.reviews.pool", fake_pool)
        fake_conn.on("select 1 from catedras", rows=[{"?column?": 1}])
        fake_conn.on("from cursos", rows=[{"?column?": 1}])
        fake_conn.on(
            "insert into catedra_reviews",
            rows=[
                {
                    "id": 1,
                    "rating": 2,
                    "comment": "meh",
                    "profesor": "Prof Z",
                    "profesor_rating": 1,
                    "anio": 2023,
                    "created_at": NOW,
                    "updated_at": NOW,
                }
            ],
            side_effect=cap,
        )
        upsert_review(
            catedra_id=42,
            body=ReviewUpsert(
                rating=2, comment="meh", profesor="Prof Z",
                profesor_rating=1, anio=2023,
            ),
            user=AuthUser(id="uid-X"),
        )
        # params = (catedra_id, user.id, rating, comment, profesor, profesor_rating, anio)
        assert captured["params"][:3] == (42, "uid-X", 2)
        assert captured["params"][4:] == ("Prof Z", 1, 2023)

    def test_escribir_no_requiere_pro(self, monkeypatch, fake_pool, fake_conn):
        # Reseñar es gratis con login: upsert no consulta la suscripción (el gate
        # Pro aplica solo a la LECTURA de más de 5 reseñas).
        monkeypatch.setattr("api.reviews.pool", fake_pool)
        fake_conn.on("select 1 from catedras", rows=[{"?column?": 1}])
        fake_conn.on("from cursos", rows=[{"?column?": 1}])
        fake_conn.on(
            "insert into catedra_reviews",
            rows=[
                {
                    "id": 1,
                    "rating": 4,
                    "comment": "ok",
                    "profesor": "Prof X",
                    "profesor_rating": 4,
                    "anio": 2024,
                    "created_at": NOW,
                    "updated_at": NOW,
                }
            ],
        )
        upsert_review(
            catedra_id=1,
            body=ReviewUpsert(
                rating=4, comment="ok", profesor="Prof X",
                profesor_rating=4, anio=2024,
            ),
            user=AuthUser(id="uid-sin-pro"),
        )
        assert not any(
            "from subscriptions" in sql.lower() for sql, _ in fake_conn.executed
        )

    def test_sin_profesor_no_valida_pertenencia(
        self, monkeypatch, fake_pool, fake_conn
    ):
        # Reseña solo de la cátedra (sin profesor): no consulta `cursos` ni
        # persiste profesor/profesor_rating.
        captured = {}

        def cap(sql, params):
            captured["params"] = params

        monkeypatch.setattr("api.reviews.pool", fake_pool)
        fake_conn.on("select 1 from catedras", rows=[{"?column?": 1}])
        fake_conn.on(
            "insert into catedra_reviews",
            rows=[
                {
                    "id": 1,
                    "rating": 3,
                    "comment": None,
                    "profesor": None,
                    "profesor_rating": None,
                    "anio": 2024,
                    "created_at": NOW,
                    "updated_at": NOW,
                }
            ],
            side_effect=cap,
        )
        resp = upsert_review(
            catedra_id=1,
            body=ReviewUpsert(rating=3, anio=2024),
            user=AuthUser(id="uid"),
        )
        assert resp.profesor is None
        assert resp.profesor_rating is None
        assert not any(
            "from cursos" in sql.lower() for sql, _ in fake_conn.executed
        )
        # params = (catedra_id, user.id, rating, comment, profesor, profesor_rating, anio)
        assert captured["params"][4:] == (None, None, 2024)

    def test_con_profesor_persiste_rating(self, monkeypatch, fake_pool, fake_conn):
        captured = {}

        def cap(sql, params):
            captured["params"] = params

        monkeypatch.setattr("api.reviews.pool", fake_pool)
        fake_conn.on("select 1 from catedras", rows=[{"?column?": 1}])
        fake_conn.on("from cursos", rows=[{"?column?": 1}])
        fake_conn.on(
            "insert into catedra_reviews",
            rows=[
                {
                    "id": 1,
                    "rating": 5,
                    "comment": None,
                    "profesor": "Prof X",
                    "profesor_rating": 2,
                    "anio": 2024,
                    "created_at": NOW,
                    "updated_at": NOW,
                }
            ],
            side_effect=cap,
        )
        resp = upsert_review(
            catedra_id=1,
            body=ReviewUpsert(
                rating=5, profesor="Prof X", profesor_rating=2, anio=2024
            ),
            user=AuthUser(id="uid"),
        )
        assert resp.profesor_rating == 2
        # La nota de la cátedra y la del profesor son independientes.
        assert resp.rating == 5
        assert captured["params"][4:] == ("Prof X", 2, 2024)


# ----------------------------- delete_review ----------------------------------

class TestDeleteReview:
    def test_propia_borra(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.reviews.pool", fake_pool)
        fake_conn.on("delete from catedra_reviews", rows=[], rowcount=1)
        resp = delete_review(catedra_id=5, user=AuthUser(id="uid"))
        assert resp == {"ok": True}
        assert fake_conn.commits == 1

    def test_sin_resena_da_404(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.reviews.pool", fake_pool)
        fake_conn.on("delete from catedra_reviews", rows=[], rowcount=0)
        with pytest.raises(HTTPException) as exc:
            delete_review(catedra_id=5, user=AuthUser(id="uid"))
        assert exc.value.status_code == 404

    def test_incluye_clerk_user_id(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.reviews.pool", fake_pool)
        fake_conn.on("delete from catedra_reviews", rows=[], rowcount=1)
        delete_review(catedra_id=8, user=AuthUser(id="uid-X"))
        sql, params = fake_conn.executed[0]
        assert "clerk_user_id = %s" in sql
        assert params == (8, "uid-X")


# ----------------------------- get_catedra_reviews ----------------------------

def _catedra_row():
    return {
        "id": 7,
        "materia_codigo": 600,
        "materia_nombre": "Materia X",
        "numero": "1",
        "titular": "Titular X",
        "cuatrimestre": "1C",
    }


class TestGetCatedraReviews:
    def test_logueado_con_mi_resena(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.reviews.pool", fake_pool)
        # Regla de suscripción primero: su SQL también contiene "clerk_user_id
        # = %s", así que debe matchear antes que la de my_review.
        fake_conn.on("from subscriptions", rows=[])
        fake_conn.on("from catedras ca", rows=[_catedra_row()])
        fake_conn.on("count(*) as cnt", rows=[
            {"rating": 5, "cnt": 2},
            {"rating": 4, "cnt": 1},
        ])
        fake_conn.on("clerk_user_id = %s", rows=[
            {"id": 99, "rating": 3, "comment": "mi reseña", "profesor": "Prof A",
             "anio": 2022, "created_at": NOW, "updated_at": NOW},
        ])
        fake_conn.on("from cursos", rows=[{"profesor": "Prof A"}, {"profesor": "Prof B"}])
        fake_conn.on("group by profesor", rows=[
            {"profesor": "Prof A", "avg_rating": 4.0, "review_count": 3},
        ])
        fake_conn.on("count(*) over()", rows=[
            {"id": 10, "rating": 5, "comment": "buenísima", "profesor": "Prof A",
             "profesor_rating": 4, "anio": 2023, "created_at": NOW,
             "updated_at": NOW, "total_count": 3},
        ])
        resp = get_catedra_reviews(catedra_id=7, page=1, user=AuthUser(id="uid"))
        assert resp.catedra.id == 7
        assert resp.review_count == 3
        assert resp.distribution[5] == 2
        assert resp.distribution[4] == 1
        assert resp.distribution[1] == 0
        assert resp.avg_rating == round((5 * 2 + 4 * 1) / 3, 2)
        assert resp.my_review is not None
        assert resp.my_review.rating == 3
        assert resp.my_review.profesor == "Prof A"
        assert resp.my_review.anio == 2022
        assert resp.total == 3
        assert len(resp.reviews) == 1
        assert resp.reviews[0].id == 10
        assert resp.reviews[0].profesor == "Prof A"
        assert resp.reviews[0].profesor_rating == 4
        # profesores: Prof A con stats, Prof B sin reseñas (count 0), ordenados.
        assert [p.profesor for p in resp.profesores] == ["Prof A", "Prof B"]
        assert resp.profesores[0].review_count == 3
        assert resp.profesores[1].review_count == 0
        assert resp.profesores[1].avg_rating is None

    def test_profesores_usan_profesor_rating(self, monkeypatch, fake_pool, fake_conn):
        # El promedio de profesores sale de AVG(profesor_rating) filtrando las
        # reseñas que puntuaron a un profesor, no del rating de la cátedra.
        monkeypatch.setattr("api.reviews.pool", fake_pool)
        fake_conn.on("from catedras ca", rows=[_catedra_row()])
        fake_conn.on("count(*) as cnt", rows=[{"rating": 5, "cnt": 1}])
        fake_conn.on("from cursos", rows=[{"profesor": "Prof A"}])
        fake_conn.on("group by profesor", rows=[
            {"profesor": "Prof A", "avg_rating": 2.0, "review_count": 1},
        ])
        fake_conn.on("count(*) over()", rows=[])
        resp = get_catedra_reviews(catedra_id=7, page=1, user=None)
        # Cátedra 5, profesor 2: el stat del profe refleja el 2.
        assert resp.avg_rating == 5.0
        assert resp.profesores[0].avg_rating == 2.0
        prof_sql = next(
            sql for sql, _ in fake_conn.executed if "group by profesor" in sql.lower()
        )
        assert "avg(profesor_rating)" in prof_sql.lower()
        assert "profesor_rating is not null" in prof_sql.lower()

    def test_anonimo_sin_mi_resena(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.reviews.pool", fake_pool)
        fake_conn.on("from catedras ca", rows=[_catedra_row()])
        fake_conn.on("count(*) as cnt", rows=[{"rating": 5, "cnt": 1}])
        fake_conn.on("from cursos", rows=[{"profesor": "Prof A"}])
        fake_conn.on("group by profesor", rows=[
            {"profesor": "Prof A", "avg_rating": 5.0, "review_count": 1},
        ])
        fake_conn.on("count(*) over()", rows=[
            {"id": 10, "rating": 5, "comment": None, "profesor": "Prof A",
             "profesor_rating": 5, "anio": 2024, "created_at": NOW,
             "updated_at": NOW, "total_count": 1},
        ])
        resp = get_catedra_reviews(catedra_id=7, page=1, user=None)
        assert resp.my_review is None
        assert resp.review_count == 1
        assert resp.total == 1

    def test_sin_resenas(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.reviews.pool", fake_pool)
        fake_conn.on("from catedras ca", rows=[_catedra_row()])
        fake_conn.on("count(*) as cnt", rows=[])
        fake_conn.on("from cursos", rows=[])
        fake_conn.on("group by profesor", rows=[])
        fake_conn.on("count(*) over()", rows=[])
        resp = get_catedra_reviews(catedra_id=7, page=1, user=None)
        assert resp.review_count == 0
        assert resp.avg_rating is None
        assert resp.total == 0
        assert resp.reviews == []
        assert resp.profesores == []

    def test_catedra_inexistente_da_404(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.reviews.pool", fake_pool)
        fake_conn.on("from catedras ca", rows=[])
        with pytest.raises(HTTPException) as exc:
            get_catedra_reviews(catedra_id=999, page=1, user=None)
        assert exc.value.status_code == 404

    def test_excluye_la_propia_del_listado(self, monkeypatch, fake_pool, fake_conn):
        # El listado paginado filtra por clerk_user_id <> uid.
        monkeypatch.setattr("api.reviews.pool", fake_pool)
        fake_conn.on("from subscriptions", rows=[])
        fake_conn.on("from catedras ca", rows=[_catedra_row()])
        fake_conn.on("count(*) as cnt", rows=[{"rating": 5, "cnt": 1}])
        fake_conn.on("clerk_user_id = %s", rows=[
            {"id": 99, "rating": 5, "comment": None, "profesor": "Prof A",
             "anio": 2024, "created_at": NOW, "updated_at": NOW},
        ])
        fake_conn.on("from cursos", rows=[{"profesor": "Prof A"}])
        fake_conn.on("group by profesor", rows=[])
        fake_conn.on("count(*) over()", rows=[])
        get_catedra_reviews(catedra_id=7, page=1, user=AuthUser(id="uid"))
        # La última query ejecutada es la del listado.
        sql, params = fake_conn.executed[-1]
        assert "clerk_user_id <> %(uid)s" in sql
        assert params["uid"] == "uid"

    # --- Gate free: solo las primeras 5 reseñas para no-Pro -------------------

    @staticmethod
    def _review_rows(n, *, total):
        return [
            {"id": i, "rating": 5, "comment": f"c{i}", "profesor": "Prof A",
             "profesor_rating": 5, "anio": 2024, "created_at": NOW,
             "updated_at": NOW, "total_count": total}
            for i in range(n)
        ]

    @staticmethod
    def _prof_rules(fake_conn):
        # Reglas de las dos queries de profesores (lista de cursos + agregados).
        fake_conn.on("from cursos", rows=[{"profesor": "Prof A"}])
        fake_conn.on("group by profesor", rows=[
            {"profesor": "Prof A", "avg_rating": 5.0, "review_count": 1},
        ])

    def test_anonimo_recorta_a_5_y_locked(self, monkeypatch, fake_pool, fake_conn):
        captured = {}
        monkeypatch.setattr("api.reviews.pool", fake_pool)
        fake_conn.on("from catedras ca", rows=[_catedra_row()])
        fake_conn.on("count(*) as cnt", rows=[{"rating": 5, "cnt": 8}])
        self._prof_rules(fake_conn)
        fake_conn.on(
            "count(*) over()",
            rows=self._review_rows(5, total=8),
            side_effect=lambda sql, params: captured.update(params=params),
        )
        resp = get_catedra_reviews(catedra_id=7, page=2, user=None)
        assert len(resp.reviews) == 5
        assert resp.locked is True
        assert resp.total == 8
        # Free no pagina: siempre las primeras 5 (limit 5, offset 0) aunque pidan page=2.
        assert captured["params"]["limit"] == 5
        assert captured["params"]["offset"] == 0

    def test_free_logueado_sin_sub_recorta(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.reviews.pool", fake_pool)
        fake_conn.on("from subscriptions", rows=[])  # sin sub activa
        fake_conn.on("from catedras ca", rows=[_catedra_row()])
        fake_conn.on("count(*) as cnt", rows=[{"rating": 5, "cnt": 9}])
        fake_conn.on("clerk_user_id = %s", rows=[])  # no tiene reseña propia
        self._prof_rules(fake_conn)
        fake_conn.on("count(*) over()", rows=self._review_rows(5, total=9))
        resp = get_catedra_reviews(catedra_id=7, page=1, user=AuthUser(id="uid"))
        assert len(resp.reviews) == 5
        assert resp.locked is True

    def test_pro_ve_pagina_completa(self, monkeypatch, fake_pool, fake_conn):
        captured = {}
        monkeypatch.setattr("api.reviews.pool", fake_pool)
        fake_conn.on("from subscriptions", rows=[{"?column?": 1}])  # Pro
        fake_conn.on("from catedras ca", rows=[_catedra_row()])
        fake_conn.on("count(*) as cnt", rows=[{"rating": 5, "cnt": 30}])
        fake_conn.on("clerk_user_id = %s", rows=[])
        self._prof_rules(fake_conn)
        fake_conn.on(
            "count(*) over()",
            rows=self._review_rows(10, total=30),
            side_effect=lambda sql, params: captured.update(params=params),
        )
        resp = get_catedra_reviews(catedra_id=7, page=2, user=AuthUser(id="uid"))
        assert resp.locked is False
        assert len(resp.reviews) == 10
        assert captured["params"]["limit"] == 10  # PAGE_SIZE
        assert captured["params"]["offset"] == 10  # (page-1) * PAGE_SIZE

    def test_filtra_por_estrellas(self, monkeypatch, fake_pool, fake_conn):
        captured = {}
        monkeypatch.setattr("api.reviews.pool", fake_pool)
        fake_conn.on("from subscriptions", rows=[{"?column?": 1}])  # Pro
        fake_conn.on("from catedras ca", rows=[_catedra_row()])
        fake_conn.on("count(*) as cnt", rows=[{"rating": 5, "cnt": 4}])
        fake_conn.on("clerk_user_id = %s", rows=[])
        self._prof_rules(fake_conn)
        fake_conn.on(
            "count(*) over()",
            rows=self._review_rows(4, total=4),
            side_effect=lambda sql, params: captured.update(params=params),
        )
        resp = get_catedra_reviews(
            catedra_id=7, page=1, rating=5, user=AuthUser(id="uid")
        )
        assert resp.total == 4
        sql = fake_conn.executed[-1][0]
        assert "rating = %(rating)s" in sql
        assert captured["params"]["rating"] == 5

    def test_filtra_por_profesor(self, monkeypatch, fake_pool, fake_conn):
        captured = {}
        monkeypatch.setattr("api.reviews.pool", fake_pool)
        fake_conn.on("from subscriptions", rows=[{"?column?": 1}])  # Pro
        fake_conn.on("from catedras ca", rows=[_catedra_row()])
        fake_conn.on("count(*) as cnt", rows=[{"rating": 5, "cnt": 4}])
        fake_conn.on("clerk_user_id = %s", rows=[])
        self._prof_rules(fake_conn)
        fake_conn.on(
            "count(*) over()",
            rows=self._review_rows(2, total=2),
            side_effect=lambda sql, params: captured.update(params=params),
        )
        resp = get_catedra_reviews(
            catedra_id=7, page=1, profesor="Prof A", user=AuthUser(id="uid")
        )
        assert resp.total == 2
        sql = fake_conn.executed[-1][0]
        assert "profesor = %(profesor)s" in sql
        assert captured["params"]["profesor"] == "Prof A"

    def test_no_pro_pocas_resenas_no_locked(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.reviews.pool", fake_pool)
        fake_conn.on("from catedras ca", rows=[_catedra_row()])
        fake_conn.on("count(*) as cnt", rows=[{"rating": 5, "cnt": 3}])
        self._prof_rules(fake_conn)
        fake_conn.on("count(*) over()", rows=self._review_rows(3, total=3))
        resp = get_catedra_reviews(catedra_id=7, page=1, user=None)
        assert resp.locked is False
        assert len(resp.reviews) == 3


# ----------------------------- list_catedras (ranking) ------------------------

class TestListCatedras:
    def test_mapea_items_y_total(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.reviews.pool", fake_pool)
        fake_conn.on("from catedras ca", rows=[
            {"catedra_id": 1, "materia_codigo": 600, "materia_nombre": "M",
             "numero": "1", "titular": "T", "cuatrimestre": "1C",
             "avg_rating": 4.5, "review_count": 10, "total_count": 2},
            {"catedra_id": 2, "materia_codigo": 600, "materia_nombre": "M",
             "numero": "2", "titular": None, "cuatrimestre": None,
             "avg_rating": None, "review_count": 0, "total_count": 2},
        ])
        resp = list_catedras(
            carrera="licenciatura-psicologia", q=None, sort="mejores", page=1
        )
        assert resp.total == 2
        assert len(resp.items) == 2
        assert resp.items[0].avg_rating == 4.5
        assert resp.items[0].review_count == 10
        assert resp.items[1].avg_rating is None
        assert resp.items[1].review_count == 0

    def test_vacio(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.reviews.pool", fake_pool)
        fake_conn.on("from catedras ca", rows=[])
        resp = list_catedras(carrera="c", q=None, sort="mejores", page=1)
        assert resp.total == 0
        assert resp.items == []

    def test_sort_y_paginacion(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.reviews.pool", fake_pool)
        fake_conn.on("from catedras ca", rows=[])
        list_catedras(carrera="c", q="giordano", sort="mas_resenas", page=3)
        sql, params = fake_conn.executed[0]
        assert "COUNT(r.id) DESC" in sql  # order de mas_resenas
        assert params["offset"] == 32  # (3-1) * RANK_PAGE_SIZE (16)
        assert params["limit"] == 16
        assert params["pattern"] == "%giordano%"

    def test_busqueda_ignora_tildes_y_mayusculas(
        self, monkeypatch, fake_pool, fake_conn
    ):
        # El patrón se pliega (NFD + strip + lower) y las columnas usan translate().
        monkeypatch.setattr("api.reviews.pool", fake_pool)
        fake_conn.on("from catedras ca", rows=[])
        list_catedras(carrera="c", q="PsicologÍA", sort="mejores", page=1)
        sql, params = fake_conn.executed[0]
        assert params["pattern"] == "%psicologia%"
        assert "translate(lower(m.nombre)" in sql

    def test_filtra_por_carrera(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.reviews.pool", fake_pool)
        fake_conn.on("from catedras ca", rows=[])
        list_catedras(carrera="profesorado-psicologia", q=None, sort="mejores", page=1)
        sql, params = fake_conn.executed[0]
        assert "m.carrera = %(carrera)s" in sql
        assert params["carrera"] == "profesorado-psicologia"

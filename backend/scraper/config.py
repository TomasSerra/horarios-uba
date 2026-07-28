import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BASE_URL = "http://academica.psi.uba.ar/Psi"
INDEX_URL = f"{BASE_URL}/Ope154_.php"
CATEDRA_URL = f"{BASE_URL}/Ver154_.php"

DATABASE_URL = os.environ.get("DATABASE_URL")

# Materias que se cursan todo el año. La fuente sólo las publica en el índice del
# 1er cuatrimestre; en el 2do desaparecen y el sweep las daría de baja. Esta lista
# es la fuente de verdad: el scraper la sincroniza a `materias.anual` en cada
# corrida, así que sacar un código de acá lo desmarca solo.
MATERIAS_ANUALES = (4, 16)  # Psicopatología, Psicoanálisis Freud
DELAY_SECONDS = float(os.environ.get("SCRAPER_DELAY_SECONDS", "0.5"))
USER_AGENT = os.environ.get(
    "SCRAPER_USER_AGENT",
    "OrganizacionHorarios/0.1",
)

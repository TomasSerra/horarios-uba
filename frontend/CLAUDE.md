# Frontend — Vite + React + TypeScript

SPA con tres rutas (`Home`, `Favoritos`, `PlanesEstudio`) que consume la API de FastAPI. shadcn/ui sobre Tailwind con primario `#861f5c`. Hosteada en Vercel.

## Estructura

```
frontend/src/
  main.tsx               entrypoint (QueryClient + Router + AlertProvider + AuthProvider)
  App.tsx                rutas (Home, Favoritos, PlanesEstudio, /pago-exitoso, /pago-error)
  pages/
    Home.tsx             selector + filtros + calendario
    Favoritos.tsx        listado de planes guardados (Pro)
    PlanesEstudio.tsx
  components/
    AuthProvider.tsx     React Context + monta <AuthDialog> global
    AuthDialog.tsx       modal login/signup sobre la app (sin nueva ruta)
    PaywallProvider.tsx  dialog de pago (MP)
    CareerProvider.tsx   monta el Context de carrera + modal forzado de selección
    CarreraSelector.tsx  UI para elegir/cambiar carrera
    Header.tsx           tabs + user menu + boton "Hacete Pro"
    Footer.tsx
    MateriaSelector.tsx  popover de búsqueda + lista de materias agregadas
    MateriaCard.tsx      card por materia con dropdowns Cátedra, Profesores, Sede (+ Comisión en anuales)
    RestriccionesPanel.tsx  días, franjas, sedes (gateado por paywall)
    CalendarioPlan.tsx   grilla 7-23 hs × días, bloques absolute-positioned
    CalendarioPlanSkeleton.tsx  loading state del calendario
    PlanNavigator.tsx    flechas + "Plan X de N"
    HistorialPopover.tsx historial de planes generados
    FavoritoFormDialog.tsx  form de nombre/descripción, compartido por guardar y editar
    ui/                  shadcn primitives (button, popover, command, dialog, input, label, ...)
  lib/
    api.ts               fetch wrapper, baseURL desde VITE_API_URL
    firebase.ts          initializeApp + getAuth + GoogleAuthProvider
    authContext.ts       tipos y React Context de auth
    useAuth.ts           hook { user, isAuthenticated, isLoading, getAccessTokenSilently, logout, openLogin }
    useMe.ts             query a /me (perfil + subscription); fuente única de ese estado
    useSubscription.ts   wrapper sobre useMe() → { isPaid, validUntil, isLoading }
    career.tsx           CareerContext + useCareer() (carrera activa, sedes disponibles)
    planEstudio.ts       armado del plan de estudio
    planHistory.ts       persistencia del historial de planes
    useIsTouchDevice.ts  detección de dispositivo táctil
    paywall.ts           hook para abrir el PaywallDialog
    alert.tsx            dialog de alert global
    types.ts             tipos compartidos con el backend (mantener en sync)
    utils.ts             cn(), helpers
  index.css              tailwind + design tokens (CSS vars)
tailwind.config.ts
```

## Cómo corre

- `npm run dev` (vite, port 5173). En docker el volumen `./frontend:/app` da HMR.
- Envs (ver `.env.example`):
  - `VITE_API_URL=http://localhost:8000` (default si falta).
  - `VITE_FIREBASE_API_KEY`, `VITE_FIREBASE_AUTH_DOMAIN`, `VITE_FIREBASE_PROJECT_ID` (de Firebase Console → Project settings → General → Web app).
- En Vercel los `VITE_FIREBASE_*` se setean como project envs. La `apiKey` de Firebase Web es pública por diseño (vive en el bundle); el control real está en "Authorized domains" de la consola.

## Auth

- `<AuthProvider>` (en [main.tsx](src/main.tsx)) inicializa Firebase y suscribe `onAuthStateChanged`. Mantiene `user`, `isLoading`, `openLogin`.
- Hooks: `useAuth()` para acceder al estado, `useMe()` para perfil + suscripción (`/me`), `useSubscription()` (wrapper de `useMe()`) para saber si es Pro, `useCareer()` para la carrera activa.
- Login UX: botón "Iniciar sesión" llama `openLogin("signin")` → abre `<AuthDialog>` (modal, sin redirect). El modal tiene tabs `signin | signup`. Google usa `signInWithPopup` con fallback a `signInWithRedirect` si el popup es bloqueado.
- Token a la API: `await getAccessTokenSilently()` (en realidad `auth.currentUser.getIdToken()`) → se manda como `Authorization: Bearer <idToken>`. Firebase auto-refresca el token.
- Logout: `logout()` (acepta y descarta cualquier arg legacy).
- Persistencia: Firebase usa IndexedDB → compartido entre tabs automáticamente.

## Convenciones

- **Castellano** en UI y comentarios. Identificadores en inglés salvo dominio (materia, cátedra, profesor, plan, franja, sede).
- **Tailwind**: utilidades inline. Sin CSS modules. Para clases dinámicas usar `cn()` de `lib/utils.ts`.
- **Estado de página** vive en `Home.tsx`. Hijos comunican via callbacks `onChange`. Sin librería de state management — la app es chica.
- **Sentinel de profesores**: `string[] | null`. `null` = todos (no filtrar), `[]` = ninguno (cero opciones), lista = subset explícito. Mantener consistente con backend.
- **Vigencia**: armar planes usa sólo la oferta vigente; reseñar usa todo. `MateriaSelector` filtra por `cant_catedras_vigentes > 0` y `MateriaCard` por `catedra.vigente`, pero `ReviewDialog` a propósito **no filtra** — se puede reseñar una cursada de un cuatrimestre que ya pasó.
- **Materias anuales** (`MateriaListItem.anual`): se cursan todo el año. En ellas `MateriaCard` no gatea el dropdown de Cátedra y suma uno de **Comisión** (Nro de comisión dentro de la cátedra elegida), ambos gratis; Profesores y Sede siguen Pro. Fijar una comisión **reduce el universo** de profesor y sede a los de esa comisión (`comisionesVisibles`): en los datos reales cada comisión trae uno o dos pares (profesor, sede) — dos cuando está partida, ver [comisiones partidas](../backend/CLAUDE.md#comisiones-partidas) —, así que los demás se ocultan en vez de listarse en la sección gris de "no disponibles", que tendría decenas de filas. `comisionesDeCatedra` agrupa por `codigo` justamente para juntar los profesores de una comisión partida bajo un solo número. Por eso hay efectos de saneo que limpian profesor y sede si quedan fuera de lo posible. El flag viaja por `SeleccionConNombre` hasta `Home`, y `seleccionUsesProFilters` / `entryUsesProFilters` ([lib/planHistory.ts](src/lib/planHistory.ts)) lo respetan para no bloquear "Generar". La hidratación desde `?q=` no strippea `ca`/`co` de una materia anual, por eso necesita la lista de materias **antes** de decidir. Detalle del backend en [backend/CLAUDE.md](../backend/CLAUDE.md#materias-anuales).
- **Toggles "usar teórico/seminario obligatorio"** (`MateriaCard`): desatan la comisión del teórico/seminario que obliga (`teorico_libre` / `seminario_libre` en `MateriaSeleccionada`, invertidos respecto del switch: prendido = atado = `false`). Son **Pro en todas las materias, anuales incluidas**, y sólo se muestran si hay obligación — `obliga_teorico` / `obliga_seminario` de la cátedra elegida, o el OR sobre las vigentes si no hay ninguna. Un efecto de saneo los apaga cuando cambiar de cátedra los deja sin nada que desatar: si no, marcarían el request como Pro sin cambiar ningún plan. Detalle de la regla en [backend/CLAUDE.md](../backend/CLAUDE.md#teórico-y-seminario-libres).
- **Colapso de la card de materia**: los dos toggles van en su propia fila (`col-span-full` + `grid-cols-1 sm:grid-cols-2`), media card cada uno de `sm` para arriba —sin importar en cuántas columnas esté la grilla de selectores— y apilados a ancho completo en mobile, como los selectores. Con eso la card pasa de 3-4 controles a 6, así que el bloque se clampea con `useClampRows` ([lib/useClampRows.ts](src/lib/useClampRows.ts)) — una fila completa en desktop (≥1024px, donde los selectores entran en una) y dos abajo de eso, con la siguiente cortada al medio, difuminado y botón "Ver más". La altura se mide en runtime (los hijos wrapean según el ancho) y el mismo hook maneja la sección de profesores de [CatedraReviews.tsx](src/pages/CatedraReviews.tsx), de donde salió el patrón.
- **`DATA_VERSION`** (`lib/api.ts`): versión del catálogo (`/carreras`, `/materias`, `/materias/{cod}/opciones`). Viaja como `?v=` en la URL **y** como versión del cache de localStorage. Como el backend sirve esos endpoints con `Cache-Control: public` ([_set_static_cache](../backend/api/main.py)), cambiar la URL es la única forma de saltear el cache del browser y del CDN: sin eso, bumpear sólo la versión de localStorage fuerza un refetch que vuelve a recibir el body viejo. **Bumpearla cuando** cambie el shape de esos payloads o cuando haga falta que los usuarios vean datos nuevos ya mismo (último bump: comisiones partidas — `/materias/{cod}/opciones` pasó a traer los profesores y sedes de todos los encuentros de una comisión, no sólo los del primero). Al arrancar un cuatrimestre el orden es **correr el scraper primero y bumpear + deployar después**: si se hace al revés queda cacheado el snapshot previo al sweep, que trae el campo de vigencia (y por eso pasa el chequeo de `fetchFresco`) pero con todas las cátedras todavía vigentes.
- **Calendario**: rango fijo `7:00 → 23:00`. `PIXELS_PER_HOUR = 32`. Las etiquetas de hora se renderizan absolute (16 etiquetas para 16 marcas, sobre 16 slots de hora). Bloques de cursos posicionados absolute con `top` y `height` calculados.
- **Botón "Generar"**: deshabilitado si no cambió ningún filtro desde la última generación. La firma se calcula con `JSON.stringify` de los inputs en `Home.tsx`.
- **Favoritos con nombre y descripción**: guardar un plan abre `FavoritoFormDialog` (nombre obligatorio, máx. 80; descripción opcional, máx. 300 — mismos límites que `FavoriteMeta` en el backend). El mismo dialog se reusa para editar desde la card, vía `mode`. **`Favorite.nombre` y `.descripcion` son nullables**: los planes guardados antes de esta feature no los tienen y la card los muestra como *"Sin nombre"* en itálica. El botón de la card de Home sigue siendo toggle — el modal aparece sólo al guardar, quitar es directo. La cabecera colapsada muestra fecha + nombre + descripción + `PlanLeyenda` compacta sin cátedra; cátedra y chips de filtros viven dentro del accordion. El calendario del accordion va con **`showCupos={false}`**: las vacantes viajan dentro de `plan_data`, así que en un favorito son las del momento en que se guardó y mostrarlas sería mentir. El prop se corta en el `useMemo` que arma `CursoConContexto` (`sinCupos` en `false` y `cuposRestantes` en `null`), no en cada render — con eso se apagan de una vez el contador, el cartel de "Sin cupos disponibles" y el triangulito sobre el bloque.
- **Nada de widgets nativos del SO**: no usar `<input type="time|date|datetime-local|month|week|color|file">`, `<select>` nativo ni `showPicker()`. Buena parte del tráfico entra por el link en bio de Instagram y TikTok, que abren la página en su navegador embebido, y ahí el picker nativo tira abajo el webview: la app se cierra y el usuario pierde todo lo cargado. Fue el caso del selector de franjas horarias, hoy resuelto con `TimeSelect` ([RestriccionesPanel.tsx](src/components/RestriccionesPanel.tsx)) sobre el `Select` de Radix. `type="number"` sí es seguro (no abre picker, solo cambia el teclado).

## Componentes shadcn

Vienen ya generados en `components/ui/`. No regenerar con CLI: editar el archivo si hace falta. Si agregás uno nuevo, copiar el patrón existente (forwardRef + cva variants).

## Tipos

`lib/types.ts` espeja modelos de Pydantic del backend. Cuando cambia algo en el backend (response shape, nuevo campo), actualizar acá. No hay generación automática.

## Verificación visual

Para cambios observables en la UI: levantar el dev server (`make up` o `npm run dev`) y verificar en browser. Si el usuario te dijo que verifica él, no levantes preview.

Si igual necesitás verificar:
- `mcp__Claude_Preview__preview_start` con `name: "horarios-frontend"` (definido en `.claude/launch.json`).
- Si Docker está usando el puerto 5173, parar el container `horarios-frontend` antes (`docker stop horarios-frontend`) y restaurarlo cuando termines.
- El backend debe estar corriendo (Docker o local) para que las requests funcionen.
- CORS solo permite `localhost:5173` y `localhost:3000` (ver [backend/api/main.py:65-69](../backend/api/main.py)). Para prod (Vercel) agregar el dominio ahí.

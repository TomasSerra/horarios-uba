import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  ArrowLeft,
  Calendar,
  Check,
  ChevronDown,
  ChevronUp,
  Gem,
  Loader2,
  MessageSquarePlus,
  Pencil,
  Star,
  Trash2,
  User,
} from "lucide-react";
import { Header } from "@/components/Header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ErrorState";
import { Pagination } from "@/components/ui/pagination";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { StarRating } from "@/components/StarRating";
import { ReviewDialog } from "@/components/ReviewDialog";
import { Seo } from "@/components/Seo";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/useAuth";
import { useSubscription } from "@/lib/useSubscription";
import { usePaywall } from "@/lib/paywall";
import { useAlert } from "@/lib/alert";
import { useClampRows } from "@/lib/useClampRows";
import { cn } from "@/lib/utils";
import type {
  CatedraReviewsResponse,
  ProfesorStats,
  ReviewItem,
} from "@/lib/types";

function catedraSubtitulo(cat: CatedraReviewsResponse["catedra"]): string {
  const partes = [`Cátedra ${cat.numero ?? cat.id}`];
  if (cat.titular) partes.push(cat.titular);
  if (cat.cuatrimestre) partes.push(cat.cuatrimestre);
  return partes.join(" · ");
}

function DistributionBars({
  distribution,
  total,
}: {
  distribution: Record<string, number>;
  total: number;
}) {
  return (
    <div className="space-y-1.5">
      {[5, 4, 3, 2, 1].map((star) => {
        const count = distribution[String(star)] ?? 0;
        const pct = total > 0 ? (count / total) * 100 : 0;
        return (
          <div key={star} className="flex items-center gap-2 text-xs">
            <span className="w-2.5 text-right text-muted-foreground">{star}</span>
            <Star className="size-3 shrink-0 fill-amber-400 text-amber-400" />
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-amber-400"
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="w-6 text-right tabular-nums text-muted-foreground">
              {count}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function ReviewCard({ review }: { review: ReviewItem }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between gap-2">
          <span className="flex items-center gap-2">
            <StarRating value={review.rating} size={15} className="shrink-0" />
            <span className="text-xs text-muted-foreground">Cátedra</span>
          </span>
          <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground">
            <Calendar className="size-3.5" />
            Cursada en {review.anio}
          </span>
        </div>
        {review.profesor && (
          <div className="mt-2 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <span className="flex min-w-0 items-center gap-1.5">
              <User className="size-4 shrink-0 text-muted-foreground" />
              <span className="truncate text-sm font-medium">
                {review.profesor}
              </span>
            </span>
            {review.profesor_rating != null && (
              <StarRating
                value={review.profesor_rating}
                size={13}
                className="shrink-0"
              />
            )}
          </div>
        )}
        {review.comment && (
          <p className="mt-2 whitespace-pre-wrap text-sm text-foreground/90">
            {review.comment}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

// Sección de profesores: ordenados por estrellas (desc), clampeada a 2 filas y
// media (la 3ra se corta al medio con un difuminado, para que se lea que hay
// más) con un botón "Ver todos". La altura se mide en runtime: los chips
// wrapean según el ancho, así que no hay un count fijo de columnas.
function ProfesoresFilter({
  profesores,
  selected,
  onSelect,
}: {
  profesores: ProfesorStats[];
  selected: string | null;
  onSelect: (profesor: string | null) => void;
}) {
  const ordenados = useMemo(() => {
    return [...profesores].sort((a, b) => {
      const ar = a.avg_rating ?? -1;
      const br = b.avg_rating ?? -1;
      if (br !== ar) return br - ar;
      if (b.review_count !== a.review_count) return b.review_count - a.review_count;
      return a.profesor.localeCompare(b.profesor);
    });
  }, [profesores]);

  // `cutFromIndex` mapea directo a `ordenados`: el hook mide los hijos en orden.
  const {
    containerRef,
    expanded,
    setExpanded,
    collapsedHeight,
    cutFromIndex,
    clamp,
  } = useClampRows(2, [ordenados]);

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold tracking-tight">
        Profesores con reseñas
      </h3>
      <div className="relative">
        <div
          ref={containerRef}
          className="flex flex-col gap-2 overflow-hidden sm:flex-row sm:flex-wrap"
          style={clamp ? { maxHeight: collapsedHeight! } : undefined}
        >
          {ordenados.map((p, i) => {
            const isSel = selected === p.profesor;
            // Chip de la 3ra fila (cortada): tocarlo despliega la lista en vez
            // de filtrar por un profesor que no se llega a leer.
            const recortado =
              clamp && cutFromIndex != null && i >= cutFromIndex;
            return (
              <button
                key={p.profesor}
                type="button"
                aria-pressed={recortado ? undefined : isSel}
                title={recortado ? "Ver todos los profesores" : undefined}
                onClick={() => {
                  if (recortado) return setExpanded(true);
                  onSelect(isSel ? null : p.profesor);
                }}
                className={cn(
                  "flex w-full items-center gap-2 rounded-xl border px-3 py-2 text-left transition-colors sm:w-auto",
                  isSel
                    ? "border-primary bg-primary/10"
                    : "border-border bg-white hover:border-primary/40 hover:bg-accent/40"
                )}
              >
                {isSel && <Check className="size-4 shrink-0 text-primary" />}
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{p.profesor}</p>
                  <div className="mt-0.5 flex items-center gap-1.5">
                    <StarRating
                      value={p.avg_rating ?? 0}
                      size={12}
                      className="shrink-0"
                    />
                    <span className="text-[11px] text-muted-foreground">
                      {p.review_count > 0
                        ? `${p.avg_rating?.toFixed(1)} · ${p.review_count} ${
                            p.review_count === 1 ? "reseña" : "reseñas"
                          }`
                        : "Sin reseñas"}
                    </span>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
        {clamp && (
          <button
            type="button"
            aria-label="Ver todos los profesores"
            onClick={() => setExpanded(true)}
            className="absolute inset-x-0 bottom-0 h-12 cursor-pointer bg-gradient-to-t from-background to-transparent"
          />
        )}
      </div>
      {collapsedHeight != null && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex items-center gap-1 text-sm font-medium text-primary hover:underline"
        >
          {expanded ? (
            <>
              <ChevronUp className="size-4" />
              Ver menos
            </>
          ) : (
            <>
              <ChevronDown className="size-4" />
              Ver todos
            </>
          )}
        </button>
      )}
    </div>
  );
}

export function CatedraReviews() {
  const { catedraId } = useParams();
  const location = useLocation();
  const id = Number(catedraId);
  const { isAuthenticated, getAccessTokenSilently } = useAuth();
  const { isPaid } = useSubscription();
  const openPaywall = usePaywall();
  const queryClient = useQueryClient();
  const showAlert = useAlert();
  const recommendationsPath =
    typeof location.state?.recommendationsPath === "string"
      ? location.state.recommendationsPath
      : "/recomendaciones";

  const [page, setPage] = useState(1);
  const [ratingFilter, setRatingFilter] = useState<number | null>(null);
  const [profesorFilter, setProfesorFilter] = useState<string | null>(null);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewInitial, setReviewInitial] = useState<{
    rating: number;
    comment: string;
    profesor: string | null;
    profesor_rating: number | null;
    anio: number;
  } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    setPage(1);
    setRatingFilter(null);
    setProfesorFilter(null);
  }, [id]);

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: [
      "catedra-reviews",
      id,
      page,
      ratingFilter,
      profesorFilter,
      isAuthenticated,
      isPaid,
    ],
    queryFn: async () => {
      const token = isAuthenticated ? await getAccessTokenSilently() : null;
      return api.getCatedraReviews(id, page, ratingFilter, profesorFilter, token);
    },
    enabled: Number.isFinite(id),
    placeholderData: keepPreviousData,
  });

  const my = data?.my_review ?? null;
  const totalPages = useMemo(
    () => (data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 0),
    [data]
  );

  // Opciones del filtro: solo las estrellas que tengan reseñas de la comunidad
  // (la distribución incluye la propia, así que la descontamos).
  const starOptions = useMemo(() => {
    if (!data) return [];
    return [5, 4, 3, 2, 1].filter((star) => {
      let count = data.distribution[String(star)] ?? 0;
      if (my && my.rating === star) count -= 1;
      return count > 0;
    });
  }, [data, my]);

  // La reseña propia se muestra también dentro del listado de la comunidad
  // (además de la sección "Tu reseña" de arriba), pero solo en la página 1 y si
  // matchea los filtros activos. Ahí es de solo lectura: editar/eliminar solo
  // desde "Tu reseña".
  const myInList = useMemo(() => {
    if (!my || page !== 1) return null;
    if (ratingFilter != null && my.rating !== ratingFilter) return null;
    // Filtro por profesor: si la reseña propia no puntuó a ese profesor, se oculta.
    if (profesorFilter != null && my.profesor !== profesorFilter) return null;
    return my;
  }, [my, page, ratingFilter, profesorFilter]);

  const displayedReviews = useMemo(
    () => (myInList ? [myInList, ...(data?.reviews ?? [])] : data?.reviews ?? []),
    [myInList, data]
  );

  function handleRatingFilterChange(value: string) {
    setRatingFilter(value === "all" ? null : Number(value));
    setPage(1);
  }

  const deleteMutation = useMutation({
    mutationFn: async () => {
      const token = await getAccessTokenSilently();
      return api.deleteCatedraReview(id, token);
    },
    onSuccess: () => {
      setConfirmDelete(false);
      queryClient.invalidateQueries({ queryKey: ["catedra-reviews", id] });
      queryClient.invalidateQueries({ queryKey: ["catedras-rank"] });
      showAlert({
        variant: "info",
        title: "Reseña eliminada",
        message: "Se quitó tu reseña.",
      });
    },
    onError: (e) =>
      showAlert({
        variant: "error",
        title: "No se pudo eliminar",
        message: (e as Error).message,
      }),
  });

  function openNew() {
    setReviewInitial(null);
    setReviewOpen(true);
  }

  function openEdit() {
    if (!my) return;
    setReviewInitial({
      rating: my.rating,
      comment: my.comment ?? "",
      profesor: my.profesor,
      profesor_rating: my.profesor_rating,
      anio: my.anio,
    });
    setReviewOpen(true);
  }

  const notFound = error instanceof ApiError && error.status === 404;

  return (
    <div className="min-h-screen bg-background">
      <Header />

      <main className="container max-w-6xl space-y-5 px-4 pb-8 pt-6 sm:px-6">
        <Link
          to={recommendationsPath}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          Recomendaciones
        </Link>

        {isLoading && !data && (
          <div className="space-y-5">
            <Skeleton className="h-44 w-full rounded-2xl" />
            <Skeleton className="h-24 w-full rounded-2xl" />
            <Skeleton className="h-20 w-full rounded-2xl" />
          </div>
        )}

        {isError && (
          <Card>
            <CardContent className="py-8">
              {notFound ? (
                <div className="flex flex-col items-center gap-3 text-center text-sm text-muted-foreground">
                  <p className="font-medium text-foreground">
                    Cátedra no encontrada
                  </p>
                  <p>Puede que ya no esté disponible.</p>
                  <Button asChild variant="outline" size="sm">
                    <Link to={recommendationsPath}>Volver a Cátedras</Link>
                  </Button>
                </div>
              ) : (
                <ErrorState
                  title="No pudimos cargar las reseñas"
                  description="Revisá tu conexión y volvé a intentar."
                  onRetry={() => refetch()}
                  retrying={isFetching}
                />
              )}
            </CardContent>
          </Card>
        )}

        {!isError && data && (
          <>
            <Seo
              title={`${data.catedra.materia_nombre} · ${catedraSubtitulo(
                data.catedra
              )} — Reseñas | Planify`}
              description={`Reseñas y puntuaciones de la comunidad sobre ${
                data.catedra.materia_nombre
              } (${catedraSubtitulo(data.catedra)}) en la Facultad de Psicología (UBA)${
                data.avg_rating != null
                  ? `. Promedio ${data.avg_rating.toFixed(1)}/5 en ${
                      data.review_count
                    } ${data.review_count === 1 ? "reseña" : "reseñas"}`
                  : ""
              }.`}
              path={`/catedras/${id}`}
              jsonLd={
                data.avg_rating != null && data.review_count > 0
                  ? {
                      "@context": "https://schema.org",
                      "@type": "Course",
                      name: `${data.catedra.materia_nombre} · ${catedraSubtitulo(
                        data.catedra
                      )}`,
                      description: `Cátedra de ${data.catedra.materia_nombre} en la Facultad de Psicología (UBA).`,
                      provider: {
                        "@type": "Organization",
                        name: "Facultad de Psicología, Universidad de Buenos Aires",
                      },
                      aggregateRating: {
                        "@type": "AggregateRating",
                        ratingValue: data.avg_rating.toFixed(1),
                        reviewCount: data.review_count,
                        bestRating: 5,
                        worstRating: 1,
                      },
                    }
                  : undefined
              }
            />
            {/* Cabecera: materia + cátedra + promedio + distribución */}
            <Card>
              <CardContent className="p-5 sm:p-6">
                <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <h1 className="text-lg font-semibold leading-tight">
                      {data.catedra.materia_nombre}
                    </h1>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {catedraSubtitulo(data.catedra)}
                    </p>
                  </div>
                  {!my && (
                    <Button
                      className="w-full shrink-0 sm:w-auto"
                      onClick={openNew}
                    >
                      <MessageSquarePlus className="size-4" />
                      Dejar reseña
                    </Button>
                  )}
                </div>

                <div className="mt-5 flex flex-col gap-5 sm:flex-row sm:items-center">
                  <div className="flex items-center gap-4 sm:flex-col sm:items-center sm:gap-1 sm:pr-6">
                    <span className="text-4xl font-bold leading-none">
                      {data.avg_rating != null ? data.avg_rating.toFixed(1) : "—"}
                    </span>
                    <div className="flex flex-col gap-1 sm:items-center">
                      <StarRating value={data.avg_rating ?? 0} size={18} />
                      <span className="text-xs text-muted-foreground">
                        {data.review_count}{" "}
                        {data.review_count === 1 ? "reseña" : "reseñas"}
                      </span>
                    </div>
                  </div>

                  <div className="flex-1 sm:border-l sm:border-border sm:pl-6">
                    {data.review_count > 0 ? (
                      <DistributionBars
                        distribution={data.distribution}
                        total={data.review_count}
                      />
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        Todavía no hay reseñas para esta cátedra.
                      </p>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Tu reseña (si ya reseñaste esta cátedra) */}
            {my && (
              <Card>
                <CardContent className="p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-xs font-semibold uppercase tracking-wide text-primary">
                        Tu reseña
                      </p>
                      <div className="mt-1.5 flex items-center gap-2">
                        <StarRating value={my.rating} size={16} className="shrink-0" />
                        <span className="text-xs text-muted-foreground">
                          Cátedra
                        </span>
                      </div>
                      {my.profesor && (
                        <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                          <span className="flex min-w-0 items-center gap-1.5">
                            <User className="size-4 shrink-0 text-muted-foreground" />
                            <span className="truncate text-sm font-medium">
                              {my.profesor}
                            </span>
                          </span>
                          {my.profesor_rating != null && (
                            <StarRating
                              value={my.profesor_rating}
                              size={13}
                              className="shrink-0"
                            />
                          )}
                        </div>
                      )}
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        Cursada {my.anio}
                      </p>
                      {my.comment && (
                        <p className="mt-2 whitespace-pre-wrap text-sm">
                          {my.comment}
                        </p>
                      )}
                    </div>
                    <div className="flex shrink-0 gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-8"
                        onClick={openEdit}
                        aria-label="Editar reseña"
                      >
                        <Pencil className="size-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-8 text-muted-foreground hover:text-destructive"
                        onClick={() => setConfirmDelete(true)}
                        aria-label="Eliminar reseña"
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )}

            <h2 className="text-lg font-semibold tracking-tight">
              Reseñas de la comunidad ({data.total + (my ? 1 : 0)})
            </h2>

            {/* Profesores con reseñas: promedio de un vistazo + filtro */}
            {data.profesores.some((p) => p.review_count > 0) && (
              <ProfesoresFilter
                profesores={data.profesores.filter((p) => p.review_count > 0)}
                selected={profesorFilter}
                onSelect={(p) => {
                  setProfesorFilter(p);
                  setPage(1);
                }}
              />
            )}

            {/* Listado de reseñas de otros */}
            <div className="space-y-3">
              {starOptions.length >= 2 && (
                <div className="flex justify-start">
                  <Select
                    value={ratingFilter == null ? "all" : String(ratingFilter)}
                    onValueChange={handleRatingFilterChange}
                  >
                    <SelectTrigger
                      className="h-9 w-auto min-w-[9rem] gap-2"
                      aria-label="Filtrar por estrellas"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">Todas las estrellas</SelectItem>
                      {starOptions.map((star) => (
                        <SelectItem key={star} value={String(star)}>
                          {star} {star === 1 ? "estrella" : "estrellas"}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}

              {displayedReviews.length === 0 ? (
                <Card>
                  <CardContent className="py-8 text-center text-sm text-muted-foreground">
                    {profesorFilter != null
                      ? "No hay reseñas de este profesor."
                      : ratingFilter != null
                      ? "No hay reseñas con esa cantidad de estrellas."
                      : data.review_count === 0
                        ? "Todavía no hay reseñas. Sé el primero en reseñar esta cátedra."
                        : my
                          ? "Nadie más reseñó esta cátedra todavía."
                          : "No hay reseñas para mostrar."}
                  </CardContent>
                </Card>
              ) : (
                <div
                  className={
                    "space-y-3 transition-opacity " +
                    (isFetching ? "opacity-60" : "")
                  }
                >
                  {displayedReviews.map((r, i) => {
                    // Gate free: la última reseña visible se desvanece con un
                    // gradient (hay más ocultas detrás del paywall).
                    const fade =
                      data.locked && i === displayedReviews.length - 1;
                    return (
                      <div key={r.id} className="relative">
                        <ReviewCard review={r} />
                        {fade && (
                          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-24 rounded-b-xl bg-gradient-to-t from-background to-transparent" />
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              {data.locked ? (
                <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed border-primary/30 bg-primary/5 px-4 py-6 text-center">
                  <Gem className="size-6 text-primary" />
                  <div className="space-y-1">
                    <p className="text-sm font-semibold">
                      Seguí leyendo las reseñas con Pro
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Con gratis ves las primeras 5 reseñas de esta cátedra.
                    </p>
                  </div>
                  <Button onClick={() => openPaywall("reviews")}>
                    <Gem className="size-4" />
                    Hacete Pro
                  </Button>
                </div>
              ) : (
                <Pagination
                  page={page}
                  totalPages={totalPages}
                  onPageChange={(p) => {
                    setPage(p);
                    window.scrollTo({ top: 0, behavior: "smooth" });
                  }}
                />
              )}
            </div>
          </>
        )}
      </main>

      {/* Dialog: escribir / editar (cátedra fija = la actual) */}
      {data && (
        <ReviewDialog
          open={reviewOpen}
          onOpenChange={setReviewOpen}
          fixedCatedra={{
            id,
            label: `${data.catedra.materia_nombre} · ${catedraSubtitulo(
              data.catedra
            )}`,
            profesores: data.profesores.map((p) => p.profesor),
          }}
          initial={reviewInitial}
          onSaved={() => {
            queryClient.invalidateQueries({ queryKey: ["catedra-reviews", id] });
            queryClient.invalidateQueries({ queryKey: ["catedras-rank"] });
          }}
        />
      )}

      {/* Dialog: confirmar eliminación */}
      <Dialog
        open={confirmDelete}
        onOpenChange={(v) => {
          if (!deleteMutation.isPending) setConfirmDelete(v);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>¿Eliminar tu reseña?</DialogTitle>
            <DialogDescription>
              Esta acción no se puede deshacer.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button
              variant="outline"
              onClick={() => setConfirmDelete(false)}
              disabled={deleteMutation.isPending}
            >
              Cancelar
            </Button>
            <Button
              variant="destructive"
              onClick={() => deleteMutation.mutate()}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Trash2 className="size-4" />
              )}
              Eliminar
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

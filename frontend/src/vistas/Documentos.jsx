import { useCallback, useEffect, useRef, useState } from "react";
import { api, fecha, pesoArchivo } from "../api";
import { Aviso, Boton, Chip, Vacio } from "../comp/Piezas";

/**
 * Los documentos del usuario.
 *
 * Procesar un PDF en CPU tarda: extraer es rápido, vectorizar no. Por eso
 * la subida devuelve enseguida y el estado se refresca solo mientras haya
 * algo en curso -- y se DEJA de refrescar cuando no lo hay, para no
 * consultar el servidor cada tres segundos toda la tarde.
 */

const ESTADOS = {
  PENDIENTE:    { tono: "gris",   texto: "en cola" },
  EXTRAYENDO:   { tono: "cian",   texto: "extrayendo texto" },
  VECTORIZANDO: { tono: "morado", texto: "vectorizando" },
  LISTO:        { tono: "verde",  texto: "listo" },
  ERROR:        { tono: "rojo",   texto: "error" },
};

const EN_CURSO = ["PENDIENTE", "EXTRAYENDO", "VECTORIZANDO"];

export default function Documentos({ resaltar }) {
  const [docs, setDocs] = useState([]);
  const [error, setError] = useState(null);
  const [subiendo, setSubiendo] = useState(false);
  const entrada = useRef(null);

  const cargar = useCallback(async () => {
    try { setDocs(await api.documentos()); }
    catch (e) { setError(e.message); }
  }, []);

  useEffect(() => { cargar(); }, [cargar]);

  useEffect(() => {
    if (!docs.some((d) => EN_CURSO.includes(d.estado))) return;
    const t = setInterval(cargar, 3000);
    return () => clearInterval(t);
  }, [docs, cargar]);

  async function subir(archivos) {
    setError(null);
    setSubiendo(true);
    try {
      for (const a of archivos) {
        const fd = new FormData();
        fd.append("archivo", a);
        await api.subirDocumento(fd);
      }
      await cargar();
    } catch (e) { setError(e.message); }
    finally { setSubiendo(false); if (entrada.current) entrada.current.value = ""; }
  }

  async function alternarCompartido(d) {
    await api.editarDocumento(d.id, { compartido: !d.compartido });
    await cargar();
  }

  async function borrar(d) {
    if (!confirm(`¿Eliminar "${d.nombre}"? Los agentes que lo usen dejarán de verlo.`)) return;
    await api.borrarDocumento(d.id);
    await cargar();
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="rotulo">Material</p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight">Documentos</h1>
          <p className="mt-1 max-w-xl text-sm text-tinta-suave">
            Lo que cargue aquí es lo que el asistente puede consultar. Es
            privado: nadie más lo ve mientras no lo comparta.
          </p>
        </div>
        <label className="btn btn-principal cursor-pointer">
          {subiendo ? "Subiendo…" : "Subir documentos"}
          <input ref={entrada} type="file" multiple hidden disabled={subiendo}
                 accept=".pdf,.docx,.xlsx,.xlsm,.txt,.md,.csv"
                 onChange={(e) => e.target.files.length && subir([...e.target.files])} />
        </label>
      </header>

      {error && <div className="mt-5"><Aviso tono="error">{error}</Aviso></div>}

      {docs.some((d) => d.tipo === "Excel" || d.tipo === "CSV") && (
        <div className="mt-5">
          <Aviso tono="alerta" titulo="Sobre las hojas de cálculo">
            Una tabla de cifras se consulta mal por aquí, y conviene saberlo
            antes de perder tiempo: el buscador encuentra por significado, y una
            fila de saldos no tiene significado que capturar. Además un modelo
            pequeño no suma ni cruza columnas de forma confiable. Para balances
            y movimientos está Analítica PUC, que los lee con un motor que
            calcula de verdad. Este asistente rinde con texto: contratos,
            normas, actas, manuales, informes.
          </Aviso>
        </div>
      )}

      <div className="mt-6 space-y-2">
        {docs.length === 0 && !error && (
          <Vacio titulo="Todavía no hay documentos">
            Acepta PDF, Word, Excel, texto plano, Markdown y CSV. Un PDF
            escaneado sin OCR no sirve: no tiene texto que extraer, y el
            sistema lo va a decir en vez de aceptarlo a medias.
          </Vacio>
        )}

        {docs.map((d) => {
          const e = ESTADOS[d.estado] ?? { tono: "gris", texto: d.estado };
          return (
            <div key={d.id}
                 className={`panel px-4 py-3 ${resaltar === d.id ? "ring-2 ring-cian" : ""}`}>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold">{d.nombre}</span>
                  <span className="block text-xs text-tinta-suave">
                    {d.tipo} · {pesoArchivo(d.bytes)} · {fecha(d.creado_en)}
                    {d.paginas ? ` · ${d.paginas} páginas` : ""}
                    {d.n_fragmentos ? ` · ${d.n_fragmentos} fragmentos` : ""}
                    {!d.es_mio && ` · compartido por ${d.propietario}`}
                  </span>
                </span>

                <Chip tono={e.tono}>{e.texto}</Chip>

                {d.es_mio && (
                  <>
                    <button onClick={() => alternarCompartido(d)}
                            title={d.compartido
                              ? "Dejar de compartir con el equipo"
                              : "Compartir con todo el equipo"}
                            className="btn btn-contorno btn-chico">
                      {d.compartido ? "Compartido" : "Privado"}
                    </button>
                    {d.estado === "ERROR" && (
                      <Boton className="btn-chico"
                             onClick={() => api.reprocesar(d.id).then(cargar)}>
                        Reintentar
                      </Boton>
                    )}
                    <button onClick={() => borrar(d)}
                            className="btn-texto text-xs hover:text-rojo">
                      Eliminar
                    </button>
                  </>
                )}
              </div>

              {d.error && (
                <p className="mt-2 rounded-[9px] bg-rojo-tenue px-3 py-2 text-xs text-rojo">
                  {d.error}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

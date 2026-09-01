import { useCallback, useEffect, useRef, useState } from "react";
import { api, preguntar, hora } from "../api";
import { Anillo, Avatar, Aviso, Boton, Chip, Vacio } from "../comp/Piezas";

/**
 * La conversación.
 *
 * Dos cosas gobiernan el diseño de esta pantalla, y las dos vienen de que
 * el modelo corre en CPU:
 *
 * · La respuesta se pinta MIENTRAS llega. Media pantalla en blanco durante
 *   treinta segundos se lee como "se rompió".
 * · Cuando el modelo está ocupado con otro usuario se dice quién y por qué,
 *   en vez de fallar con un error genérico. Es una cola, no una avería.
 */

/** Convierte las marcas [1] [2] del texto en anclas visibles.
 *
 *  Se hace aquí y no con markdown completo a propósito: lo único que hay
 *  que resaltar es la cita, y meter un renderizador entero para eso trae
 *  más superficie de la que resuelve. */
function ConCitas({ texto, citas, onCita }) {
  const partes = String(texto).split(/(\[\d+\])/g);
  return (
    <>
      {partes.map((p, i) => {
        const m = p.match(/^\[(\d+)\]$/);
        if (!m) return <span key={i}>{p}</span>;
        const n = Number(m[1]);
        const cita = (citas ?? []).find((c) => c.n === n);
        if (!cita) return <span key={i}>{p}</span>;
        return (
          <button key={i} className="cita" onClick={() => onCita(cita)}
                  title={`${cita.documento}${cita.pagina ? `, página ${cita.pagina}` : ""}`}>
            {n}
          </button>
        );
      })}
    </>
  );
}

/** Solo los fragmentos que la respuesta CITA de verdad.
 *
 *  Antes se listaban los ocho recuperados, citados o no. Una respuesta que
 *  decía "eso no está en los documentos" aparecía debajo de ocho fuentes,
 *  como si se apoyara en ellas. Eso es exactamente lo que este sistema
 *  existe para evitar: la apariencia de respaldo donde no lo hay.
 *
 *  Lo consultado pero no citado se declara aparte, en una línea, porque el
 *  usuario tiene derecho a saber sobre qué material se respondió -- pero no
 *  bajo el rótulo de "fuentes". */
function Fuentes({ texto, citas, onCita }) {
  if (!citas?.length) return null;
  const usados = new Set(
    [...String(texto).matchAll(/\[(\d+)\]/g)].map((m) => Number(m[1])));
  const citadas = citas.filter((c) => usados.has(c.n));

  // En ámbar y no en gris pequeño: este es el aviso que más importa de toda
  // la pantalla. Una respuesta sin citas puede estar inventada de principio a
  // fin, y suena igual de segura que una correcta. Si se pierde entre el
  // texto fino, no sirve de nada haberla detectado.
  if (!citadas.length) {
    return (
      <p className="mt-2 rounded-[9px] border-l-[3px] border-ambar bg-ambar-tenue
                    px-3 py-2 text-xs leading-relaxed text-ambar">
        <strong>Sin respaldo documental.</strong> La respuesta no cita ningún
        fragmento: se consultaron {citas.length} y ninguno sustenta lo dicho.
        Trátela como una opinión del modelo, no como algo leído en sus
        documentos.
      </p>
    );
  }

  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5">
      <span className="rotulo">Fuentes</span>
      {citadas.map((c) => (
        <button key={c.n} onClick={() => onCita(c)}
                className="rounded-full border border-regla bg-papel px-2 py-0.5
                           text-[11px] text-tinta-media hover:border-cian hover:text-cian-hondo">
          <span className="cifra">[{c.n}]</span> {c.documento}
          {c.pagina ? ` · p. ${c.pagina}` : ""}
        </button>
      ))}
      {citadas.length < citas.length && (
        <span className="text-[11px] text-tinta-suave">
          · se consultaron {citas.length - citadas.length} fragmento(s) más que
          la respuesta no citó
        </span>
      )}
    </div>
  );
}

export default function Chat({ agentes, onIrA }) {
  const [convs, setConvs] = useState([]);
  const [activa, setActiva] = useState(null);
  const [mensajes, setMensajes] = useState([]);
  const [enVuelo, setEnVuelo] = useState(null);   // respuesta que se está escribiendo
  const [citasVuelo, setCitasVuelo] = useState([]);
  const [nota, setNota] = useState(null);         // aviso del recuperador
  // En qué va la respuesta. El servidor avisa cuándo terminó de buscar, así
  // que no hay que adivinarlo: decirle al usuario "buscando" durante el
  // minuto que el modelo pasa LEYENDO es señalar el paso equivocado, y la
  // pantalla parece colgada.
  const [fase, setFase] = useState(null);         // buscando | leyendo
  const [seg, setSeg] = useState(0);
  const [texto, setTexto] = useState("");
  const [error, setError] = useState(null);
  const [ocupado, setOcupado] = useState(false);
  const [agenteNuevo, setAgenteNuevo] = useState("");
  const fondo = useRef(null);
  const aborto = useRef(null);

  const cargarConvs = useCallback(async () => {
    setConvs(await api.conversaciones());
  }, []);

  useEffect(() => { cargarConvs().catch((e) => setError(e.message)); }, [cargarConvs]);

  // Un contador mientras se espera. En CPU la primera palabra puede tardar
  // un minuto; sin un número que avance, cualquiera concluye que se rompió.
  useEffect(() => {
    if (!ocupado) return;
    const t = setInterval(() => setSeg((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [ocupado]);

  // Al final de cada trozo, seguir el hilo hacia abajo.
  useEffect(() => {
    fondo.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [mensajes, enVuelo]);

  async function abrir(id) {
    aborto.current?.abort();
    setError(null); setEnVuelo(null); setNota(null); setCitasVuelo([]);
    const c = await api.conversacion(id);
    setActiva(c);
    setMensajes(c.mensajes);
  }

  async function nueva() {
    const c = await api.nuevaConversacion(agenteNuevo || null);
    await cargarConvs();
    await abrir(c.id);
  }

  async function borrar(id, e) {
    e.stopPropagation();
    await api.borrarConversacion(id);
    if (activa?.id === id) { setActiva(null); setMensajes([]); }
    await cargarConvs();
  }

  async function enviar(e) {
    e?.preventDefault();
    const pregunta = texto.trim();
    if (!pregunta || ocupado || !activa) return;

    setTexto(""); setError(null); setNota(null);
    setCitasVuelo([]); setEnVuelo(""); setOcupado(true);
    setFase("buscando"); setSeg(0);
    setMensajes((m) => [...m, { id: `local-${Date.now()}`, rol: "usuario",
                                texto: pregunta, creado_en: new Date().toISOString() }]);

    aborto.current = new AbortController();
    let acumulado = "";
    let citas = [];
    try {
      await preguntar(activa.id, pregunta, (ev) => {
        if (ev.tipo === "contexto") {
          citas = ev.citas ?? [];
          setCitasVuelo(citas);
          setNota({ modo: ev.modo, criterio: ev.criterio,
                    documentos: ev.documentos, aviso: ev.aviso });
          setFase("leyendo");
        } else if (ev.tipo === "texto") {
          acumulado += ev.texto;
          setEnVuelo(acumulado);
        } else if (ev.tipo === "ocupado") {
          setError(ev.texto);
        } else if (ev.tipo === "error") {
          setError(ev.texto);
        }
      }, aborto.current.signal);

      if (acumulado.trim()) {
        setMensajes((m) => [...m, { id: `resp-${Date.now()}`, rol: "asistente",
                                    texto: acumulado, citas,
                                    creado_en: new Date().toISOString() }]);
      }
      await cargarConvs();
    } catch (err) {
      if (err.name !== "AbortError") setError(err.message);
    } finally {
      setEnVuelo(null);
      setOcupado(false);
      setFase(null);
    }
  }

  function verCita(cita) {
    onIrA?.("documentos", cita.documento_id);
  }

  const agenteDe = (c) => c.agente;

  return (
    <div className="mx-auto grid h-[calc(100vh-4.2rem)] max-w-7xl
                    grid-cols-1 gap-4 px-4 py-4 md:grid-cols-[17rem_1fr]">

      {/* ------------------------------------------- conversaciones */}
      <aside className="panel hidden min-h-0 flex-col overflow-hidden md:flex">
        <div className="border-b border-regla p-3">
          <select value={agenteNuevo} onChange={(e) => setAgenteNuevo(e.target.value)}
                  className="w-full px-2 py-1.5 text-xs">
            <option value="">Sin agente · todos mis documentos</option>
            {agentes.map((a) => (
              <option key={a.id} value={a.id}>{a.nombre}</option>
            ))}
          </select>
          <Boton tono="principal" onClick={nueva} className="mt-2 w-full justify-center btn-chico">
            Nueva conversación
          </Boton>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {convs.length === 0 && (
            <p className="px-2 py-6 text-center text-xs text-tinta-suave">
              Todavía no hay conversaciones.
            </p>
          )}
          {convs.map((c) => (
            <button key={c.id} onClick={() => abrir(c.id)}
                    className={`group mb-1 block w-full rounded-[9px] px-3 py-2 text-left
                                ${activa?.id === c.id ? "bg-morado-tenue" : "hover:bg-papel-hondo"}`}>
              <span className="flex items-start gap-2">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{c.titulo}</span>
                  <span className="block truncate text-[11px] text-tinta-suave">
                    {c.agente ? c.agente : "sin agente"} · {c.n_mensajes} mensajes
                  </span>
                </span>
                <span onClick={(e) => borrar(c.id, e)}
                      className="hidden shrink-0 text-tinta-suave hover:text-rojo group-hover:block">
                  ×
                </span>
              </span>
            </button>
          ))}
        </div>
      </aside>

      {/* ------------------------------------------------- diálogo */}
      <section className="panel flex min-h-0 flex-col overflow-hidden">
        {!activa ? (
          <div className="flex flex-1 items-center justify-center p-8">
            <div className="max-w-md text-center">
              <div className="mx-auto w-fit"><Anillo tam={56} /></div>
              <h2 className="mt-5 text-2xl font-bold tracking-tight texto-marca">
                Pregunte sobre lo suyo
              </h2>
              <p className="mt-2 text-sm leading-relaxed text-tinta-suave">
                Cargue documentos, elija un agente si quiere acotar la
                búsqueda, y abra una conversación. Cada respuesta trae la
                cita del fragmento del que salió.
              </p>
              <Boton tono="principal" onClick={nueva} className="mt-6">
                Empezar
              </Boton>
            </div>
          </div>
        ) : (
          <>
            <header className="flex items-center gap-3 border-b border-regla px-4 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{activa.titulo}</p>
                <p className="text-[11px] text-tinta-suave">
                  {agenteDe(activa)
                    ? <>Agente <span className="text-morado">{agenteDe(activa).nombre}</span></>
                    : "Sin agente · consulta todos sus documentos"}
                </p>
              </div>
              {ocupado && <Chip tono="morado">generando</Chip>}
            </header>

            <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-5">
              {mensajes.map((m) => (
                <div key={m.id}
                     className={`flex gap-2.5 ${m.rol === "usuario" ? "justify-end" : ""}`}>
                  {m.rol !== "usuario" && <div className="pt-1"><Anillo tam={26} /></div>}
                  <div className={`max-w-[46rem] px-4 py-2.5 text-sm leading-relaxed
                                   ${m.rol === "usuario" ? "burbuja-usuario" : "burbuja-asistente"}`}>
                    <p className="whitespace-pre-wrap">
                      {m.rol === "usuario"
                        ? m.texto
                        : <ConCitas texto={m.texto} citas={m.citas} onCita={verCita} />}
                    </p>
                    {m.rol !== "usuario" &&
                      <Fuentes texto={m.texto} citas={m.citas} onCita={verCita} />}
                    <p className={`mt-1 text-[10px] ${m.rol === "usuario"
                        ? "text-white/60" : "text-tinta-suave"}`}>
                      {hora(m.creado_en)}
                      {m.ms ? ` · ${(m.ms / 1000).toFixed(1)} s` : ""}
                      {m.modelo ? ` · ${m.modelo}` : ""}
                    </p>
                  </div>
                </div>
              ))}

              {enVuelo !== null && (
                <div className="flex gap-2.5">
                  <div className="pt-1"><Anillo tam={26} girando /></div>
                  <div className="burbuja-asistente max-w-[46rem] px-4 py-2.5 text-sm leading-relaxed">
                    {enVuelo ? (
                      <p className="whitespace-pre-wrap escribiendo">
                        <ConCitas texto={enVuelo} citas={citasVuelo} onCita={verCita} />
                      </p>
                    ) : fase === "buscando" ? (
                      <p className="text-xs text-tinta-suave">
                        Buscando en sus documentos… <span className="cifra">{seg}s</span>
                      </p>
                    ) : (
                      <p className="text-xs text-tinta-suave">
                        Encontrados <span className="cifra">{citasVuelo.length}</span>{" "}
                        fragmentos. El modelo los está leyendo…{" "}
                        <span className="cifra">{seg}s</span>
                        <span className="mt-1 block text-tinta-suave/70">
                          Este es el paso lento: en este servidor el modelo lee
                          el contexto antes de escribir la primera palabra.
                        </span>
                      </p>
                    )}
                  </div>
                </div>
              )}

              {nota?.muestra && (
                <Aviso tono="alerta" titulo="Esta pregunta pide contar o enumerar">
                  El asistente solo ve unos pocos fragmentos del documento,
                  nunca el documento entero. No puede contar, sumar ni listar
                  de forma exhaustiva: lo que responda es lo que salió en esa
                  muestra, y el número real casi con seguridad es mayor. Para
                  contar o totalizar un balance está Analítica PUC.
                </Aviso>
              )}
              {nota && (nota.aviso || nota.documentos === 0) && (
                <Aviso tono="alerta" titulo="Sobre esta búsqueda">
                  {nota.aviso ?? "No hay documentos procesados en el alcance."}
                </Aviso>
              )}
              {error && <Aviso tono="error">{error}</Aviso>}

              <div ref={fondo} />
            </div>

            <form onSubmit={enviar} className="border-t border-regla p-3">
              <div className="flex items-end gap-2">
                <textarea
                  value={texto} rows={1} disabled={ocupado}
                  placeholder="Escriba su pregunta…"
                  onChange={(e) => setTexto(e.target.value)}
                  onKeyDown={(e) => {
                    // Enter envía; Shift+Enter hace párrafo. Es lo que la
                    // gente espera de un chat.
                    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); enviar(); }
                  }}
                  className="max-h-40 min-h-[2.6rem] flex-1 resize-y px-3 py-2 text-sm"
                />
                <Boton tono="principal" type="submit" disabled={ocupado || !texto.trim()}>
                  {ocupado ? "…" : "Enviar"}
                </Boton>
              </div>
              {nota && !nota.aviso && nota.documentos > 0 && (
                <p className="mt-1.5 text-[11px] text-tinta-suave">
                  Última búsqueda: {nota.criterio} ({nota.documentos}) · por {nota.modo}.
                </p>
              )}
            </form>
          </>
        )}
      </section>
    </div>
  );
}

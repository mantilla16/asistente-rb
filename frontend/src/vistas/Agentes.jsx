import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { Aviso, Boton, Campo, Chip, Modal, Vacio } from "../comp/Piezas";

/**
 * Agentes: un encargo permanente con instrucciones y documentos propios.
 *
 * Lo que hace útil a un agente no son sus instrucciones sino su ALCANCE.
 * Un agente atado a cuatro documentos responde mejor que uno con acceso a
 * cuatrocientos, porque el recuperador tiene menos ruido donde perderse.
 * Por eso el selector de documentos ocupa la mitad del formulario.
 */

const PLANTILLAS = [
  {
    nombre: "Consultor de un proceso",
    descripcion: "Explica cómo se hace algo según los documentos cargados",
    instrucciones:
      "Explicas procesos a partir de la documentación cargada. Cuando alguien " +
      "pregunte cómo se hace algo, responde con los pasos en orden, citando el " +
      "fragmento de cada paso. Si un paso no está documentado, dilo en su lugar " +
      "en vez de completarlo con lo que suele hacerse.",
  },
  {
    nombre: "Investigador de un tema",
    descripcion: "Resume y contrasta lo que dicen varios documentos",
    instrucciones:
      "Investigas un tema sobre el material cargado. Resume lo que dicen las " +
      "fuentes, y cuando dos se contradigan dilo explícitamente citando ambas " +
      "en vez de escoger una. Distingue siempre lo que afirman los documentos " +
      "de lo que es interpretación tuya.",
  },
  {
    nombre: "Lector de normas",
    descripcion: "Responde citando el artículo o numeral exacto",
    instrucciones:
      "Respondes consultas sobre normativa. Cita siempre el artículo, numeral " +
      "o párrafo exacto. No parafrasees una obligación: transcríbela y luego " +
      "explícala. Si la norma cargada no cubre el caso, dilo.",
  },
];

const VACIO = {
  nombre: "", descripcion: "", instrucciones: "", modelo: "",
  temperatura: 0.3, fragmentos: 8, compartido: false, documentos: [],
};

export default function Agentes({ onCambio }) {
  const [agentes, setAgentes] = useState([]);
  const [docs, setDocs] = useState([]);
  const [editando, setEditando] = useState(null);
  const [error, setError] = useState(null);

  const cargar = useCallback(async () => {
    try {
      setAgentes(await api.agentes());
      setDocs((await api.documentos()).filter((d) => d.estado === "LISTO"));
    } catch (e) { setError(e.message); }
  }, []);

  useEffect(() => { cargar(); }, [cargar]);

  async function abrir(a) {
    if (!a) return setEditando({ ...VACIO });
    const completo = await api.agente(a.id);
    setEditando({
      ...completo,
      modelo: completo.modelo ?? "",
      descripcion: completo.descripcion ?? "",
      temperatura: Number(completo.temperatura),
      documentos: completo.documentos.map((d) => String(d.id)),
    });
  }

  async function guardar() {
    setError(null);
    const a = editando;
    const datos = {
      nombre: a.nombre.trim(), descripcion: a.descripcion?.trim() || null,
      instrucciones: a.instrucciones ?? "", modelo: a.modelo?.trim() || null,
      temperatura: Number(a.temperatura), fragmentos: Number(a.fragmentos),
      compartido: !!a.compartido, documentos: a.documentos,
    };
    try {
      if (a.id) await api.editarAgente(a.id, datos);
      else await api.crearAgente(datos);
      setEditando(null);
      await cargar();
      onCambio?.();
    } catch (e) { setError(e.message); }
  }

  async function borrar(a) {
    if (!confirm(`¿Eliminar el agente "${a.nombre}"?`)) return;
    await api.borrarAgente(a.id);
    await cargar();
    onCambio?.();
  }

  const alternarDoc = (id) => setEditando((e) => ({
    ...e,
    documentos: e.documentos.includes(id)
      ? e.documentos.filter((x) => x !== id)
      : [...e.documentos, id],
  }));

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="rotulo">Configuración</p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight">Agentes</h1>
          <p className="mt-1 max-w-xl text-sm text-tinta-suave">
            Un agente son unas instrucciones y un conjunto de documentos.
            Acotar el alcance es lo que lo hace preciso.
          </p>
        </div>
        <Boton tono="principal" onClick={() => abrir(null)}>Crear agente</Boton>
      </header>

      {error && <div className="mt-5"><Aviso tono="error">{error}</Aviso></div>}

      <div className="mt-6 grid gap-3 sm:grid-cols-2">
        {agentes.length === 0 && (
          <div className="sm:col-span-2">
            <Vacio titulo="Todavía no hay agentes">
              Sin agente, el asistente consulta todos sus documentos. Un
              agente sirve para acotarlo a un tema y darle una forma de
              responder.
            </Vacio>
          </div>
        )}

        {agentes.map((a) => (
          <div key={a.id} className="panel flex flex-col p-4">
            <div className="flex items-start gap-2">
              <div className="min-w-0 flex-1">
                <p className="truncate font-semibold">{a.nombre}</p>
                <p className="mt-0.5 line-clamp-2 text-xs leading-relaxed text-tinta-suave">
                  {a.descripcion || "Sin descripción"}
                </p>
              </div>
              {a.compartido && <Chip tono="cian">compartido</Chip>}
            </div>

            <div className="mt-3 flex flex-wrap gap-1.5">
              <Chip tono="gris">
                {a.n_documentos > 0
                  ? `${a.n_documentos} documento${a.n_documentos === 1 ? "" : "s"}`
                  : "todos mis documentos"}
              </Chip>
              <Chip tono="gris">{a.fragmentos} fragmentos</Chip>
              <Chip tono="gris">temp {Number(a.temperatura).toFixed(2)}</Chip>
            </div>

            {a.es_mio ? (
              <div className="mt-3 flex gap-2">
                <Boton className="btn-chico" onClick={() => abrir(a)}>Editar</Boton>
                <button onClick={() => borrar(a)}
                        className="btn-texto text-xs hover:text-rojo">Eliminar</button>
              </div>
            ) : (
              <p className="mt-3 text-[11px] text-tinta-suave">
                Compartido por {a.propietario}
              </p>
            )}
          </div>
        ))}
      </div>

      {editando && (
        <Modal titulo={editando.id ? "Editar agente" : "Nuevo agente"}
               onCerrar={() => setEditando(null)}>
          {!editando.id && (
            <div className="mb-4">
              <p className="rotulo mb-1.5">Empezar desde una plantilla</p>
              <div className="flex flex-wrap gap-1.5">
                {PLANTILLAS.map((p) => (
                  <button key={p.nombre}
                          onClick={() => setEditando((e) => ({ ...e, ...p }))}
                          className="btn btn-contorno btn-chico">
                    {p.nombre}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="space-y-4">
            <Campo etiqueta="Nombre">
              <input type="text" value={editando.nombre}
                     onChange={(e) => setEditando({ ...editando, nombre: e.target.value })}
                     className="w-full px-3 py-2 text-sm" />
            </Campo>

            <Campo etiqueta="Descripción"
                   ayuda="Para que usted lo reconozca en la lista. No se le manda al modelo.">
              <input type="text" value={editando.descripcion ?? ""}
                     onChange={(e) => setEditando({ ...editando, descripcion: e.target.value })}
                     className="w-full px-3 py-2 text-sm" />
            </Campo>

            <Campo etiqueta="Instrucciones"
                   ayuda="Cómo debe comportarse. Las reglas de citación del sistema mandan
                          sobre esto: un agente no puede pedirle al modelo que afirme sin citar.">
              <textarea rows={6} value={editando.instrucciones}
                        onChange={(e) => setEditando({ ...editando, instrucciones: e.target.value })}
                        className="w-full px-3 py-2 text-sm leading-relaxed" />
            </Campo>

            <div className="grid gap-4 sm:grid-cols-3">
              <Campo etiqueta="Modelo" ayuda="Vacío usa el del servidor.">
                <input type="text" value={editando.modelo ?? ""} placeholder="por defecto"
                       onChange={(e) => setEditando({ ...editando, modelo: e.target.value })}
                       className="w-full px-3 py-2 text-sm" />
              </Campo>
              <Campo etiqueta="Temperatura" ayuda="Baja para consultar; alta para redactar.">
                <input type="number" min="0" max="1" step="0.05"
                       value={editando.temperatura}
                       onChange={(e) => setEditando({ ...editando, temperatura: e.target.value })}
                       className="w-full px-3 py-2 text-sm" />
              </Campo>
              <Campo etiqueta="Fragmentos" ayuda="Más contexto cuesta tiempo en CPU.">
                <input type="number" min="2" max="20"
                       value={editando.fragmentos}
                       onChange={(e) => setEditando({ ...editando, fragmentos: e.target.value })}
                       className="w-full px-3 py-2 text-sm" />
              </Campo>
            </div>

            <Campo etiqueta="Documentos del agente"
                   ayuda="Sin ninguno marcado, consulta todos los suyos. Marcar unos pocos
                          mejora las respuestas: el buscador tiene menos ruido donde perderse.">
              <div className="max-h-56 overflow-y-auto rounded-[9px] border border-regla p-2">
                {docs.length === 0 && (
                  <p className="px-2 py-3 text-xs text-tinta-suave">
                    No hay documentos procesados todavía.
                  </p>
                )}
                {docs.map((d) => (
                  <label key={d.id}
                         className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5
                                    text-sm hover:bg-papel-hondo">
                    <input type="checkbox"
                           checked={editando.documentos.includes(String(d.id))}
                           onChange={() => alternarDoc(String(d.id))} />
                    <span className="min-w-0 flex-1 truncate">{d.nombre}</span>
                    <span className="shrink-0 text-[11px] text-tinta-suave">
                      {d.n_fragmentos} fragmentos
                    </span>
                  </label>
                ))}
              </div>
            </Campo>

            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={!!editando.compartido}
                     onChange={(e) => setEditando({ ...editando, compartido: e.target.checked })} />
              Compartir este agente con el equipo
            </label>
          </div>

          <div className="mt-5 flex justify-end gap-2">
            <Boton onClick={() => setEditando(null)}>Cancelar</Boton>
            <Boton tono="principal" onClick={guardar} disabled={!editando.nombre.trim()}>
              Guardar
            </Boton>
          </div>
        </Modal>
      )}
    </div>
  );
}

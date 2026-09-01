import { useCallback, useEffect, useState } from "react";
import { api, fecha } from "../api";
import { Avatar, Aviso, Boton, Campo, Chip, Modal } from "../comp/Piezas";

/** Administración de usuarios. Solo la ve un ADMIN; el backend lo vuelve a
 *  comprobar, porque esconder un botón no es un control de acceso. */
export default function Usuarios() {
  const [usuarios, setUsuarios] = useState([]);
  const [error, setError] = useState(null);
  const [nuevo, setNuevo] = useState(null);
  const [clave, setClave] = useState(null);   // {id, nombre}

  const cargar = useCallback(async () => {
    try { setUsuarios(await api.usuarios()); }
    catch (e) { setError(e.message); }
  }, []);

  useEffect(() => { cargar(); }, [cargar]);

  async function crear() {
    setError(null);
    try {
      await api.crearUsuario(nuevo);
      setNuevo(null);
      await cargar();
    } catch (e) { setError(e.message); }
  }

  async function alternarActivo(u) {
    await api.editarUsuario(u.id, { activo: !u.activo });
    await cargar();
  }

  async function guardarClave(nueva) {
    setError(null);
    try {
      await api.reiniciarClave(clave.id, nueva);
      setClave(null);
    } catch (e) { setError(e.message); }
  }

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="rotulo">Administración</p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight">Usuarios</h1>
          <p className="mt-1 text-sm text-tinta-suave">
            Desactivar cierra las sesiones abiertas de esa persona de inmediato.
          </p>
        </div>
        <Boton tono="principal"
               onClick={() => setNuevo({ usuario: "", nombre: "", correo: "",
                                         clave: "", rol: "MIEMBRO" })}>
          Crear usuario
        </Boton>
      </header>

      {error && <div className="mt-5"><Aviso tono="error">{error}</Aviso></div>}

      <div className="mt-6 space-y-2">
        {usuarios.map((u) => (
          <div key={u.id} className="panel flex flex-wrap items-center gap-3 px-4 py-3">
            <Avatar nombre={u.nombre} />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold">{u.nombre}</p>
              <p className="truncate text-xs text-tinta-suave">
                <span className="cifra">{u.usuario}</span>
                {u.correo ? ` · ${u.correo}` : ""}
                {u.ultimo_acceso ? ` · último ingreso ${fecha(u.ultimo_acceso)}`
                                 : " · nunca ha entrado"}
              </p>
            </div>
            <Chip tono={u.rol === "ADMIN" ? "morado" : "gris"}>{u.rol}</Chip>
            <Chip tono={u.activo ? "verde" : "rojo"}>
              {u.activo ? "activo" : "inactivo"}
            </Chip>
            <Boton className="btn-chico"
                   onClick={() => setClave({ id: u.id, nombre: u.nombre })}>
              Contraseña
            </Boton>
            <button onClick={() => alternarActivo(u)} className="btn-texto text-xs">
              {u.activo ? "Desactivar" : "Activar"}
            </button>
          </div>
        ))}
      </div>

      {nuevo && (
        <Modal titulo="Nuevo usuario" onCerrar={() => setNuevo(null)} ancho="max-w-lg">
          <div className="space-y-4">
            <Campo etiqueta="Usuario" ayuda="Con esto entra. No se puede cambiar después.">
              <input type="text" value={nuevo.usuario} autoFocus
                     onChange={(e) => setNuevo({ ...nuevo, usuario: e.target.value })}
                     className="w-full px-3 py-2 text-sm" />
            </Campo>
            <Campo etiqueta="Nombre completo">
              <input type="text" value={nuevo.nombre}
                     onChange={(e) => setNuevo({ ...nuevo, nombre: e.target.value })}
                     className="w-full px-3 py-2 text-sm" />
            </Campo>
            <Campo etiqueta="Correo (opcional)">
              <input type="email" value={nuevo.correo}
                     onChange={(e) => setNuevo({ ...nuevo, correo: e.target.value })}
                     className="w-full px-3 py-2 text-sm" />
            </Campo>
            <div className="grid grid-cols-2 gap-4">
              <Campo etiqueta="Contraseña" ayuda="Mínimo 8 caracteres.">
                <input type="text" value={nuevo.clave}
                       onChange={(e) => setNuevo({ ...nuevo, clave: e.target.value })}
                       className="w-full px-3 py-2 text-sm" />
              </Campo>
              <Campo etiqueta="Rol">
                <select value={nuevo.rol}
                        onChange={(e) => setNuevo({ ...nuevo, rol: e.target.value })}
                        className="w-full px-3 py-2 text-sm">
                  <option value="MIEMBRO">MIEMBRO</option>
                  <option value="ADMIN">ADMIN</option>
                </select>
              </Campo>
            </div>
          </div>
          <div className="mt-5 flex justify-end gap-2">
            <Boton onClick={() => setNuevo(null)}>Cancelar</Boton>
            <Boton tono="principal" onClick={crear}
                   disabled={!nuevo.usuario || !nuevo.nombre || nuevo.clave.length < 8}>
              Crear
            </Boton>
          </div>
        </Modal>
      )}

      {clave && <DialogoClave persona={clave} onCerrar={() => setClave(null)}
                              onGuardar={guardarClave} />}
    </div>
  );
}

function DialogoClave({ persona, onCerrar, onGuardar }) {
  const [valor, setValor] = useState("");
  return (
    <Modal titulo={`Contraseña de ${persona.nombre}`} onCerrar={onCerrar}
           ancho="max-w-md">
      <Campo etiqueta="Nueva contraseña"
             ayuda="Al cambiarla se cierran todas sus sesiones abiertas.">
        <input type="text" value={valor} autoFocus
               onChange={(e) => setValor(e.target.value)}
               className="w-full px-3 py-2 text-sm" />
      </Campo>
      <div className="mt-5 flex justify-end gap-2">
        <Boton onClick={onCerrar}>Cancelar</Boton>
        <Boton tono="principal" onClick={() => onGuardar(valor)}
               disabled={valor.length < 8}>
          Cambiar
        </Boton>
      </div>
    </Modal>
  );
}
